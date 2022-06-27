#!/bin/bash

set -e

if [ -z "$GITHUB_TOKEN" ]; then
	echo "Missing GITHUB_TOKEN environment variable"
	exit 1
fi

if [ -z "$EMAIL_TOKEN" ]; then
	echo "Missing EMAIL_TOKEN environment variable"
	exit 1
fi

if [ -z "$PATCHWORK_TOKEN" ]; then
	echo "Missing PATCHWORK_TOKEN environment variable"
	exit 1
fi

# Input Params
PW_KEY_STR=$1
BASE_BRANCH=$2
CONFIG=$3
PATCHWORK_ID=$4
EMAIL_MESSAGE=$5
USER=$6

echo "Input Parameters"
echo "1: PW_KEY_STR = $PW_KEY_STR"
echo "2: BASE_BRANCH = $BASE_BRANCH"
echo "3: CONFIG = $CONFIG"
echo "4: PATCHWORK_ID = $PATCHWORK_ID"
echo "5: EMAIL_MESSAGE = $EMAIL_MESSAGE"
echo "6: USER = $USER"

echo "Add the workspace dir to GIT safe directory"
git config --global --add safe.directory $GITHUB_WORKSPACE

echo "Setup GIT CONFIG USER"
git config --global user.name "$GITHUB_ACTOR"
git config --global user.email "$GITHUB_ACTOR@users.noreply.github.com"

git config pw.server https://patchwork.kernel.org/api/1.2
git config pw.project https://patchwork.kernel.org/project/iwd/list
git config pw.token $PATCHWORK_TOKEN

echo "Set GIT REMOTE URL for $GITHUB_REPOSITORY"
git remote set-url origin "https://x-access-token:$GITHUB_TOKEN@github.com/$GITHUB_REPOSITORY"
echo "GIT BRANCH -A"
git branch -a
echo "GIT REMOTE -V"
git remote -v

export HUB_VERBOSE=1
export HUB_PROTOCOL=https
export GITHUB_USER="$GITHUB_ACTOR"

pip install git-pw

echo "HUB_PROTOCOL=$HUB_PROTOCOL"
echo "GITHUB_USER=$GITHUB_USER"

echo "########## RUN ##########"
/pw-to-pr.py -e $EMAIL_MESSAGE -a $PATCHWORK_ID -u $USER -c $CONFIG -r $GITHUB_REPOSITORY -b $BASE_BRANCH -k $PW_KEY_STR -s $PWD
