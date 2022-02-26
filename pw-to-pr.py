#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import smtplib
import requests
import argparse
import re
import tempfile
import subprocess
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from git import Repo
from typing import List
from github import Github, Repository
from enum import Enum

# Globals
github_repo = None
github_pulls = None

# Constants
PW_BASE_URL = "https://patchwork.kernel.org/api"
PW_PROJECT_ID = "395"
PR_TITLE_PREFIX='PW_SID'

PW_URL_API_BASE = None


EMAIL_MESSAGE = '''This is an automated email and please do not reply to this email.

Dear Submitter,

Thank you for submitting the patches to the linux bluetooth mailing list.
While preparing the CI tests, the patches you submitted couldn't be applied to the current HEAD of the repository.

----- Output -----
{}

Please resolve the issue and submit the patches again.


---
Regards,
Linux Bluetooth

'''


def requests_url(url: str):
    """ Helper function to request GET with URL """
    resp = requests.get(url)
    if resp.status_code != 200:
        raise requests.HTTPError("GET {}".format(resp.status_code))
    return resp


def requests_post(url, headers, content):
    """ Helper function to post data to URL """

    resp = requests.post(url, content, headers=headers)
    if resp.status_code != 201:
        raise requests.HTTPError("POST {}".format(resp.status_code))

    return resp


def cmd_run(cmd: List[str], shell=False, add_env=None, cwd=None):
    """
    Run a command.
    """

    env = os.environ.copy()
    if add_env:
        env.update(add_env)
        print("Update Environment Variable: %s" % add_env)

    print("CMD: %s" % cmd)
    proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=env, cwd=cwd,)
    stdout, stderr = proc.communicate()
    stdout = stdout.decode("utf-8", "ignore")
    stderr = stderr.decode("utf-8", "ignore")
    proc.stdout.close()
    proc.stderr.close()

    print("\tRETCODE=%d" % proc.returncode)
    print("\tSTDOUT:\n\t%s" % stdout.replace('\n', '\n\t'))
    print("\tSTDERR:\n\t%s" % stderr.replace('\n', '\n\t'))

    if proc.returncode != 0:
        return (proc.returncode, "", stderr)

    return (0, stdout, stderr)


def git_checkout(branch: str, cwd: str, create_branch=False) -> bool:
    cmd = ["git", "checkout"]
    if create_branch:
        cmd += ["-b", branch]
    else:
        cmd += [branch]

    (ret, stdout, stderr) = cmd_run(cmd, cwd=cwd)
    if ret != 0:
        print("ERROR: failed to checkout")
        return False

    print("Source checkout to %s" % branch)
    return True


def git_push(remote: str, branch: str, cwd: str, force=False) -> bool:
    cmd = ['git', 'push', remote, branch]
    if force:
        cmd += ['--force']
    (ret, stdout, stderr) = cmd_run(cmd, cwd=cwd)
    if ret != 0:
        print("ERROR: failed to push")
        return False
    print("Branch(%s) pushed to repo" % branch)
    return True


def git_am(patch: str, cwd: str):
    cmd = ['git', 'am', patch]
    return cmd_run(cmd, cwd=cwd)


def git_am_abort(cwd):
    cmd = ['git', 'am', '--abort']
    return cmd_run(cmd, cwd=cwd)


def pw_get_series(id: int) -> dict:
    """
    Get full details of series based on id
    """
    url = '{}/series/{}'.format(PW_BASE_URL, str(id))
    print("URL: %s" % url)

    resp = requests_url(url)
    return resp.json()


def pw_get_patch(id: int) -> dict:
    """
    Get full details of patch based on id
    """
    print("Get Patch from Patchwork: %s" % id)
    url = '{}/patches/{}'.format(PW_BASE_URL, str(id))
    print("URL: %s" % url)

    resp = requests_url(url)
    return resp.json()


def pw_get_patches_by_state(states: list) -> list:
    """
    Get patches from the Patchwork based on the target states
    """

    patches = []

    print("Get patches by state: %s" % states)
    url = '{}/patches/?project={}&archived=0'.format(PW_BASE_URL, PW_PROJECT_ID)

    # Add states
    for state in states:
        url += '&state={}'.format(state)
    print("URL: %s" % url)

    while True:
        resp = requests_url(url)
        patches = patches + resp.json()

        # Read next page
        if "next" not in resp.links:
            break

        print("Read next page")
        url = resp.links["next"]["url"]

    print("Read all patches: Total = %d" % len(patches))

    return patches


def pw_submit_check(patch_id: int, state: int, context: str, description: str, target_url=None):
    """
    Post checks(test results) to the patch)

    patch_id: target patch
    state: 1: Pass, 2: Warning, 3: Fail
    context: check title
    description: check content
    target_url: link of the reult. Default=None
    dry_run: if True, don't send the result. Default=False
    """

    print("Submit result(state=%d) to Patchwork/Check" % state)

    # Build URL for check
    url = '{}/patches/{}/checks/'.format(PW_BASE_URL, str(patch_id))
    print("URL: %s" % url)

    headers = {}
    if 'PATCHWORK_TOKEN' not in os.environ:
        print("ERROR: Unable to find PATCHWORK_TOKEN in environment")
        return None

    if not target_url:
        target_url = ""

    token = os.environ['PATCHWORK_TOKEN']
    headers['Authorization'] = f'Token {token}'

    content = {
        'user': 104215,
        'state': state,
        'target_url': target_url,
        'context': context,
        'description': description
    }
    print("Content: %s" % content)

    req = requests_post(url, headers, content)
    return req.json()


def github_create_pr(title: str, body: str, base: str, head: str):
    print("Creating PR:\n base:{} <-- head:{}\ntitle: {}\nbody\n{}".format(base, head, title, body))
    pr = github_repo.create_pull(title=title, body=body, base=base, head=head,
                                 maintainer_can_modify=True)
    print("PR created: PR:{} URL:{}".format(pr.number, pr.url))
    return None


def github_close_pr(pr_id):
    """
    Delete PR and delete associated branch
    """
    pr = github_repo.get_pull(pr_id)
    pr_head_ref = pr.head.ref
    print("Closing PR({})".format(pr_id))

    pr.edit(state="closed")
    print("PR({}) is closed".format(pr_id))

    git_ref = github_repo.get_git_ref("heads/{}".format(pr_head_ref))
    git_ref.delete()
    print("Branch({}) is removed".format(pr_head_ref))


def github_pr_exist(id: int) -> bool:
    """
    Check is the PR for series(id) is already exist in github
    """
    id_str = 'PW_SID:{}'.format(str(id))
    for pull in github_pulls:
        if  re.search(id_str, pull.title, re.IGNORECASE):
            return True
    return False


def email_sendmail(config: dict, from_addr: str, to_addr: str, message: str):
    """
    Send email
    """
    print("Send email to %s" % to_addr)

    if 'EMAIL_TOKEN' not in os.environ:
        print("ERROR: Missing EMAIL_TOKEN in Environment. Skip sending")
        return
    print("EMAIL_TOKEN found")

    try:
        session = smtplib.SMTP(config['server'], config['port'])
        print("SMTP session is created")
        session.ehlo()
        if config['starttls']:
            session.starttls()
            print("SMTP TLS is set")
        session.ehlo()
        session.login(from_addr, os.environ['EMAIL_TOKEN'])
        print("SMTP login done")
        session.sendmail(from_addr, to_addr, message.as_string())
        print("SMTP sent successfully")
    except Exception as e:
        print("ERROR: Exception: {}".format(e))
    finally:
        session.quit()

    print("SMTP DONE")


def email_compose(config, series, content):

    to_addr = []

    if not config['enable']:
        print("Email is DISABLED. Skip sending email")
        return

    # Create Message
    message = MIMEMultipart()
    message['Subject'] = 'RE: ' + series['name']
    message['Reply-To'] = config['default-to']

    from_addr = config['user']
    if config['only-maintainers']:
        maintainers = config['maintainers']
        to_addr.extend(maintainers)
    else:
        to_addr.append(config['default-to'])
        to_addr.append(series['submitter']['email'])

    message['From'] = from_addr
    message['To'] = ", ".join(to_addr)

    # Extract the msgid from the first patch
    patch_1 = series['patches'][0]
    message.add_header('In-Reply-To', patch_1['msgid'])
    message.add_header('References', patch_1['msgid'])

    message.attach(MIMEText(content, 'plain'))
    print("Email Message:\n{}".format(message))

    email_sendmail(config, from_addr, to_addr, message)


def get_new_series(states: list) -> dict:
    """
    Get new series from the PW
    """
    series_dict = {}

    patches = pw_get_patches_by_state(states)
    if len(patches) == 0:
        print("No patches found")
        return series_dict

    for patch in patches:
        # Skip if patch has no series
        if 'series' not in patch:
            continue

        # # Skip if the patch is already checked
        # if not ignore_check and 'check' in patch and patch['check'] != 'pending':
        #     print("Patch %d is already checked" % patch['id'])
        #     continue

        for series in patch['series']:
            # Check if series id already exist
            if series['id'] not in series_dict:
                series_dict.update({series['id']: pw_get_series(series['id'])})
                print("Found new series %s" % series['id'])
            else:
                print("Series %s already exist" % series['id'])

    print("List of Series: ")
    for id in series_dict:
        print("   %s" % id)

    return series_dict


def series_checked(series: dict) -> bool:
    """
    If the series is already checked, return True otherwise return False
    """
    patch_1 = pw_get_patch(series['patches'][0]['id'])
    if patch_1['check'] == 'pending':
        # No check
        return False
    return True


def save_series_patches(id: int, series: dict, root_dir: str) -> str:
    """
    Save series to the temp folder
    """
    # Create series_id folder
    series_path = os.path.join(root_dir, str(id))
    if not os.path.exists(series_path):
        os.makedirs(series_path)
    print("Series PATH: %s" % series_path)

    # Save patches
    if "patches" not in series:
        print("ERROR: No patches found in Series %s" % id)
        return series_path

    count = 0

    for patch in series['patches']:
        resp = requests_url(patch['mbox'])
        patch_file_name = "{}.patch".format(patch['id'])
        patch_file_path = os.path.join(root_dir, patch_file_name)
        print("Patch %s saved to %s" % (patch_file_name, patch_file_path))
        with open(patch_file_path, 'wb') as f:
            f.write(resp.content)
            count += 1

    print("Series %s: Total patch count: %s" % (id, count))

    return series_path


def create_series_dir(id: int, root_dir: str) -> str:
    """
    Create a directory for series with series id
    """
    series_path = os.path.join(root_dir, str(id))
    if not os.path.exists(series_path):
        os.makedirs(series_path)

    return series_path


def create_pr(series: dict, base: str, head: str):

    title = '[{}:{}] {}'.format(PR_TITLE_PREFIX, series["id"], series["name"])

    # Use the commit of the patch for pr body
    patch_1 = pw_get_patch(series['patches'][0]['id'])
    pr = github_create_pr(title, patch_1['content'], base, head)
    return pr


def get_pw_sid(pr_title) -> int:
    """
    Parse PR title prefix and get PatchWork Series ID
    PR Title Prefix = "[PW_S_ID:<series_id>] XXXXX"
    """
    try:
        sid = re.search(r'^\[PW_SID:([0-9]+)\]', pr_title).group(1)
    except AttributeError:
        print("ERROR: Unable to find the series_id from title %s" % pr_title)
        return 0
    return int(sid)


def patch_get_file_list(patch: str) -> list:
    """
    Parse patch to get the file list
    """

    file_list = []

    # If patch has no contents, return empty file
    if patch == None:
        print("WARNING: No file found in patch")
        return file_list

    # split patch(in string) to list of string by newline
    lines = patch.split('\n')
    for line in lines:
        # Use --- (before) instead of +++ (after).
        # If new file is added, --- is /dev/null and can be ignored
        # If file is removed, file in --- still exists in the tree
        # The corner case is if the patch adds new files. Even in this case
        # even if new files are ignored, Makefile should be changed as well
        # so it still can be checked.
        if re.search(r'^\-\-\- ', line):
            # it has new file. Ignore the file. It doesn't exist anyway.
            if line.find('dev/null'):
                print("New file is added. Ignore in the file list")
                continue

            # Trim the '--- /'
            file_list.append(line[line.find('/')+1:])

    return file_list


def series_get_file_list(series: dict) -> list:
    """
    Get the list of files from the patches in the series.
    """

    file_list = []

    for patch in series['patches']:
        full_patch = pw_get_patch(patch['id'])
        file_list += patch_get_file_list(full_patch['diff'])

    return file_list


def filter_repo_type(repo_detail: dict, series: dict, src_dir: str) -> bool:
    """
    Check if the series belong to this repository

    if the series[name] has exclude string
        return False
    if the series[name] has include string
        return True
    get file list from the patch in series
    if the file exist
        return True
    else
        return False
    """

    print("Check repo type for this series[name]=%s" % series['name'])

    # Check Exclude string
    for str in repo_detail['exclude']:
        if re.search(str, series['name'], re.IGNORECASE):
            print("Found EXCLUDE string: %s" % str)
            return False

    # Check Include string
    for str in repo_detail['include']:
        if re.search(str, series['name'], re.IGNORECASE):
            print("Found INCLUDE string: %s" % str)
            return True

    # Get file list from the patches in the series
    file_list = series_get_file_list(series)
    if len(file_list) == 0:
        # Something is not right.
        print("ERROR: No files found in the series/patch")
        return False
    print("Files in Series=%s" % file_list)

    # File exist in source tree?
    for filename in file_list:
        file_path = os.path.join(src_dir, filename)
        if not os.path.exists(file_path):
            print("File not found: %s" % filename)
            return False

    # Files exist in the source tree
    print("Files exist in the source tree.")
    return True


def init_config(config_file: str) -> dict:
    """
    Read config_file
    """

    config_path = os.path.abspath(config_file)
    if not os.path.exists(config_path):
        print("ERROR: Unable to find config file: %s" % config_path)
        return None

    print("Loading config file: %s" % config_path)
    with open(config_path, 'r') as f:
        config=json.load(f)
    return config


def init_github(repo: str) -> Repository:
    """
    Initialize the github repository
    """
    global github_repo, github_pulls

    print("Initializing Github Repo(%s)" % repo)
    github_repo = Github(os.environ['GITHUB_TOKEN']).get_repo(repo)
    github_pulls = github_repo.get_pulls()


def parse_args() -> argparse.ArgumentParser:
    """ Parse input argument """
    ap = argparse.ArgumentParser(description="PatchWork client that saves the"
                                             "patches from the series")
    ap.add_argument('-c', '--config-file', default='./config.json',
                    help='Configuration file')
    ap.add_argument("-p", "--patch-state", nargs='+', default=['1', '2'],
                    help="State of patch to query. Default is \'1\' and \'2\'")
    ap.add_argument("-r", "--repo", required=True,
                    help="Name of base repo where the PR is pushed. "
                         "Use <OWNER>/<REPO> format. i.e. bluez/bluez")
    ap.add_argument("-b", "--branch", default="workflow",
                    help="Name of branch in base_repo where the PR is pushed. "
                         "Use <BRANCH> format. i.e. master")
    ap.add_argument("-k", "--key-str", default="kernel",
                    help="Specify the string to distinguish the repo type: "
                         "kernel or user")
    ap.add_argument('-s', '--src-dir', required=True,
                    help='Source directory')
    ap.add_argument('-i', '--ignore-check', action='store_true', default=False,
                    help='Ignore the patch\'s check status and process all new '
                         'series in the Patchwork. Debug only')
    ap.add_argument('-n', '--no-update-check', action='store_true', default=False,
                    help='Do not upload the patchwork status. Debug/Local only')
    ap.add_argument('-d', '--dry-run', action='store_true', default=False,
                    help='Run it without uploading the result')
    return ap.parse_args()


def main():

    new_series = []
    args = parse_args()

    # Make sure args.key_str is valid
    if args.key_str != 'kernel' and args.key_str != 'user':
        print("ERROR: Invalid repo_type: %s" % args.key_str)
        sys.exit(1)

    config = init_config(args.config_file)
    if config == None:
        sys.exit(2)

    init_github(args.repo)

    # Source Directory
    src_dir = args.src_dir

    # Get series dict { id: full detail of series[id] }
    new_series = get_new_series(args.patch_state)
    if len(new_series) == 0:
        print("No new patches found. Done. Exit.")
        return

    temp_root_dir = tempfile.TemporaryDirectory().name
    print("Temp Series ROOT: %s" % temp_root_dir)

    for id in new_series:
        series = new_series[id]
        print("\n##### Series: %s #####" % id)

        if not args.ignore_check and series_checked(series):
            # Check if this series is already checked
            print("Series is already checked. Skip")
            continue

        # If the series subject doesn't have the key-str, ignore it.
        # Sometimes, the name have null value. If that's the case, use the
        # name from the first patch and update to series name
        if series['name'] == None:
            patch_1 = series['patches'][0]
            series['name'] = patch_1['name']
            print("Series[\'name\'] is updated to \'%s\'" % series['name'])

        if not filter_repo_type(config['repo_details'][args.key_str], series, src_dir):
            print("NOT for this repo: %s" % args.key_str)
            continue

        # If the PR is already created in github, no need to continue
        if github_pr_exist(id):
            print("PR is already created")
            continue

        # Save series/patches to the local directory
        series_dir = create_series_dir(id, temp_root_dir)
        print("Series PATH: %s" % series_dir)

        # Reset source branch to base branch
        if not git_checkout(args.branch, src_dir):
            # No need to continue
            print("ERROR: Failed: git checkout %s" % args.branch)
            continue

        # Create branch for series
        if not git_checkout(str(id), src_dir, create_branch=True):
            print("ERROR: Failed: git checkout -b %s" % id)
            continue

        verdict = True
        content = ""

        for patch in series['patches']:
            print("[Patch: %s]" % patch['id'])
            resp = requests_url(patch['mbox'])
            patch_name = "{}.patch".format(patch['id'])
            patch_path = os.path.join(series_dir, patch_name)
            with open(patch_path, 'wb') as f:
                f.write(resp.content)
            print("Patch saved to %s" % patch_path)

            # Apply patch
            (ret, stdout, stderr) = git_am(patch_path, src_dir)
            if ret != 0:
                # git am fail. notify and abort
                verdict = False
                if args.dry_run:
                    print("Dry-Run. Skip pw_submit_check(fail)")
                else:
                    if args.no_update_check:
                        print("No-Update-Check. Skip pw_submit_check(fail)")
                    else:
                        pw_submit_check(patch['id'], 3, "pre-ci_am", stderr)

                # Abort git am
                git_am_abort(src_dir)

                # Update the contents for email body
                content = EMAIL_MESSAGE.format(stderr)
                print("CONTENT:")
                print("\t{}".format(content.replace('\n', '\t\n')))
                break

            # Success.
            if args.dry_run:
                print("Dry-Run. Skip pw_submit_check(pass)")
            else:
                if args.no_update_check:
                    print("No-Update-Check. Skip pw_submit_check(success)")
                else:
                    pw_submit_check(patch['id'], 1, "pre-ci_am", "Success")

        if not verdict:
            print("PRE-CI_AM failed. Notify the submitter")

            # Send email
            if args.dry_run:
                print("Dry-Run. Skip email_compose")
            else:
                email_compose(config['email'], series, content)
            continue

        print("PRE-CI_AM Success. Creating CI for next step")

        # create CI
        if args.dry_run:
            print("Dry-Run. Skip create_pr")
        else:
            # Push branch to Github first
            if not git_push('origin', str(id), src_dir):
                print("ERROR: Failed to push the source to github")
                print("ERROR: Skip creating Pull Request")
                continue

            create_pr(series, args.branch, str(id))

    print("\n##### DONE #####\n")

    print("----- CLEAN UP PULL REQUEST -----")
    # Clean up Pull Request
    for pr in github_pulls:
        print("\n{}".format(pr))
        pw_sid = get_pw_sid(pr.title)
        print("PW_SID: %s" % pw_sid)

        if pw_sid in new_series:
            print("SID found in PR list. Keep PR.")
            continue

        print("SID not found in PR list. Close PR")

        if args.dry_run:
            print("Dry-Run. Skip github_close_pr")
        else:
            github_close_pr(pr.number)

    print("\n----- DONE -----")

if __name__ == "__main__":
    main()
