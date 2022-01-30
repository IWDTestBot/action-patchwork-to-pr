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

echo "Input Parameters"
echo "1: PW_KEY_STR = $PW_KEY_STR"
echo "2: BASE_BRANCH = $BASE_BRANCH"

echo "Setup GIT CONFIG USER"
git config user.name "$GITHUB_ACTOR"
git config user.email "$GITHUB_ACTOR@users.noreply.github.com"

echo "Set GIT REMOTE URL for $GITHUB_REPOSITORY"
git remote set-url origin "https://x-access-token:$GITHUB_TOKEN@github.com/$GITHUB_REPOSITORY"
echo "GIT BRANCH -A"
git branch -a
echo "GIT REMOTE -V"
git remote -v

export HUB_VERBOSE=1
export HUB_PROTOCOL=https
export GITHUB_USER="$GITHUB_ACTOR"

echo "HUB_PROTOCOL=$HUB_PROTOCOL"
echo "GITHUB_USER=$GITHUB_USER"

echo "########## RUN ##########"
/pw-to-pr.py -c /config.json -r $GITHUB_REPOSITORY -b $BASE_BRANCH -k $PW_KEY_STR -s $PWD
