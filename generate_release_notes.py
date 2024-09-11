#!/usr/bin/env python3
"""
This script generates release notes using the GitHub Release API then prints it to
standard output. You must be logged into GitHub using the `gh` CLI tool or provide a
GitHub token via `GITHUB_TOKEN` environment variable.

Usage:

    generate-release-notes.py [<release-tag>] [<previous-tag>]

The release tag defaults to `preview` but often should be set to the new version:

    generate-release-notes.py "2.3.0"

The target defaults to `main` but can be set to a different commit or branch:

    generate-release-notes.py "2.3.0" "my-test-branch"

The previous tag defaults to the last tag, but can be set to a different tag to view
release notes for a different release. In this case, the target must be provided too.

    generate-release-notes.py "2.3.3" "main" "2.3.2"
"""
import os
import re
import shutil
import subprocess
import sys
import json
from datetime import datetime

import requests

REPO_ORG = "amirraouf"
REPO_NAME = "gh-release-automation"
DEFAULT_TAG = "main"
TOKEN_REGEX = re.compile(r"Token:\s(.*)")
ENTRY_REGEX = re.compile(r"^\* (.*) by @(.*) in (.*)$", re.MULTILINE)

# API URLs
BASE_URL = f"https://api.github.com/repos/{REPO_ORG}/{REPO_NAME}"
RELEASES_URL = f"{BASE_URL}/releases"

def get_github_token() -> str:
    """
    Retrieve the current GitHub token from the `gh` CLI.
    """
    if "GITHUB_TOKEN" in os.environ:
        return os.environ["GITHUB_TOKEN"]

    if not shutil.which("gh"):
        print(
            "You must provide a GitHub access token via GITHUB_TOKEN or have the gh CLI installed."
        )
        exit(1)

    gh_auth_status = subprocess.run(
        ["gh", "auth", "status", "--show-token"], capture_output=True
    )
    output = gh_auth_status.stderr.decode()
    if not gh_auth_status.returncode == 0:
        print(
            "Failed to retrieve authentication status from GitHub CLI:", file=sys.stderr
        )
        print(output, file=sys.stderr)
        exit(1)

    match = TOKEN_REGEX.search(output)
    if not match:
        print(
            f"Failed to find token in GitHub CLI output with regex {TOKEN_REGEX.pattern!r}:",
            file=sys.stderr,
        )
        print(output, file=sys.stderr)
        exit(1)

    return match.groups()[0]

# Headers for authentication
HEADERS = {
    "Authorization": f"token {get_github_token()}",
    "Accept": "application/vnd.github.v3+json",
}


def get_release_by_tag(tag_name):
    print(tag_name)
    """Fetch the release information by tag name."""
    url = f"{RELEASES_URL}/tags/{tag_name}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        release = response.json()
        return release
    else:
        print(f"Error fetching release: {response.status_code} {response.text}")
        return None


def generate_release_body(since):
    """get merged prs and generate release body"""
    since = datetime.fromisoformat(since)
    merged_prs = get_merged_prs(since, get_github_token())
    release_body = ""
    for pr in merged_prs:
        print(f"### Ticket\n{pr['ticket_no']}")
        release_body += f"## {pr['ticket_no']} - {pr['title']}\n"
        
        for section, bullet_points in pr['release_notes'].items():
            if bullet_points:
                print(f"### {section}")
                release_body += f"### {section}\n"
                for bullet_point in bullet_points:
                    print(f"- {bullet_point}")
                    release_body += f"- {bullet_point}\n"
    return release_body


def update_release(release_id, new_name=None, new_body=None, draft=None, prerelease=None):
    """Update the release information."""
    url = f"{RELEASES_URL}/{release_id}"

    payload = {}
    if new_name:
        payload["name"] = new_name
    if new_body:
        payload["body"] = new_body
    if draft is not None:
        payload["draft"] = draft
    if prerelease is not None:
        payload["prerelease"] = prerelease

    response = requests.patch(url, headers=HEADERS, data=json.dumps(payload))

    if response.status_code == 200:
        print(f"Release updated successfully: {response.json()['name']}")
    else:
        print(f"Error updating release: {response.status_code} {response.text}")


def extract_jira_ticket_no(pr_body):
    # Regular expression to match Jira ticket numbers
    jira_ticket_section = re.compile(r"### Ticket")
    # Splitting the PR body by lines
    lines = pr_body.splitlines()
    for i, line in enumerate(lines):
        section_match = jira_ticket_section.match(line)
        if section_match:
            # Extract the ticket numbers from the section
            return lines[i + 1]
        continue
    return ""


def extract_changelog(pr_body):
    # Find the release notes section in the PR body
    release_notes = {
        "Added": [],
        "Changed": [],
        "Deprecated": [],
        "Removed": [],
        "Fixed": [],
        "Security": []
    }

    # Regular expressions to match the sections and their bullet points
    section_regex = re.compile(r"### (\w+)")
    bullet_point_regex = re.compile(r"- (.+)")

    # Splitting the PR body by lines
    lines = pr_body.splitlines()

    current_section = None

    for line in lines:
        section_match = section_regex.match(line)
        bullet_point_match = bullet_point_regex.match(line)

        if section_match:
            current_section = section_match.group(1)
            # Ensuring we only process known sections
            if current_section not in release_notes:
                current_section = None
        elif bullet_point_match and current_section:
            release_notes[current_section].append(bullet_point_match.group(1).strip())

    return release_notes


# Function to get all merged PRs since the last release
def get_merged_prs(since, github_token):
    merged_prs = []
    page = 1
    pulls_url = f'https://api.github.com/repos/{REPO_ORG}/{REPO_NAME}/pulls?state=closed&base=master&per_page=100'

    while True:
        response = requests.get(f'{pulls_url}&page={page}', headers={'Authorization': f'token {github_token}'})
        prs = response.json()

        if not prs:
            break

        for pr in prs:
            merged_at = datetime.strptime(pr['merged_at'], '%Y-%m-%dT%H:%M:%SZ') if pr['merged_at'] else None
            if merged_at and merged_at > since:
                merged_prs.append(
                    {
                        "title": pr['title'], 
                        "release_notes": extract_changelog(pr['body']),
                        "ticket_no": extract_jira_ticket_no(pr['body']), 
                        "merged_at": merged_at
                    }
                )

        page += 1

    return merged_prs


if __name__ == "__main__":
    print(sys.argv)
    new_release = get_release_by_tag(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TAG)
    print(new_release)
    prev_release = get_release_by_tag(sys.argv[2] if len(sys.argv) > 2 else None)
    print(prev_release)
    
    if new_release:
        release_id = new_release["id"]

        # Generate the release notes
        print(type(prev_release["published_at"]))
        release_body = generate_release_body(prev_release["created_at"] if prev_release else None)

        # Update the release (update name and body, set to draft or prerelease if needed)
        update_release(
            release_id,
            None,  # Optional: new release title
            release_body,  # Optional: new release body
            draft=False,  # Set to True if you want to make it a draft release
            prerelease=False  # Set to True if you want to mark it as a prerelease
        )
