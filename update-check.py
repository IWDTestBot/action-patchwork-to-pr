#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import argparse
import requests

PW_BASE_URL = "https://patchwork.kernel.org/api"

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


def pw_get_patch(id: int) -> dict:
    """
    Get full details of patch based on id
    """
    print("Get Patch from Patchwork: %s" % id)
    url = '{}/patches/{}'.format(PW_BASE_URL, str(id))
    print("URL: %s" % url)

    resp = requests_url(url)
    return resp.json()


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


def parse_args() -> argparse.ArgumentParser:
    """ Parse input argument """
    ap = argparse.ArgumentParser(description="Update PW check manually")
    ap.add_argument('-p', '--patch-id', required=True, type=int,
                    help='Patch ID to update the check')
    ap.add_argument('-s', '--state', required=True, type=int,
                    help="State. 1: Pass, 2: Warning, 3: Fail")
    ap.add_argument('-t', '--target-url', default="",
                    help="Target URL where the check's result points to")
    ap.add_argument('-c', '--context', required=True,
                    help="Check Name")
    ap.add_argument('-d', '--description', required=True,
                    help="Test result/description")
    return ap.parse_args()


def main():

    args = parse_args()

    # Validate Argument
    try:
        patch = pw_get_patch(args.patch_id)
    except Exception as e:
        print("ERROR: Unable to get patch: %s" % e)
        sys.exit(1)

    if args.state != 1 and args.state != 2 and args.state != 3:
        print("ERROR: Invalid State: %s" % args.state)
        sys.exit(1)

    if args.context.find(" ") >= 0:
        print("ERROR: Context No Space Allowed")
        sys.exit(1)

    ret = pw_submit_check(args.patch_id, args.state, args.context, args.description, target_url=args.target_url)
    print(ret)

if __name__ == "__main__":
    main()
