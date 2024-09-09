#!/usr/bin/env python3
"""
This script generates release notes using the GitHub Release API then prints it to
standard output. You must be logged into GitHub using the `gh` CLI tool or provide a
GitHub token via `GITHUB_TOKEN` environment variable.

Usage:

    generate-release-notes.py [<release-tag>] [<target>] [<previous-tag>]

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
from datetime import datetime

import requests

REPO_ORG = "amirraouf"
REPO_NAME = "gh-release-automation"
DEFAULT_TAG = "main"

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

TOKEN_REGEX = re.compile(r"Token:\s(.*)")
ENTRY_REGEX = re.compile(r"^\* (.*) by @(.*) in (.*)$", re.MULTILINE)


def get_release_by_tag(tag_name):
    """Fetch the release information by tag name."""
    url = f"{RELEASES_URL}/tags/{tag_name}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        release = response.json()
        return release
    else:
        print(f"Error fetching release: {response.status_code} {response.text}")
        return None


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

    response = requests.patch(url, headers=headers, data=json.dumps(payload))

    if response.status_code == 200:
        print(f"Release updated successfully: {response.json()['name']}")
    else:
        print(f"Error updating release: {response.status_code} {response.text}")


def generate_release_notes(
    repo_org: str,
    repo_name: str,
    tag_name: str,
    github_token: str,
    previous_tag: str = None,
):
    """
    Generate release notes using the GitHub API.
    """
    request = {"tag_name": tag_name, "target_commitish": target_commit}
    if previous_tag:
        request["previous_tag_name"] = previous_tag

    response = requests.post(
        f"https://api.github.com/repos/{repo_org}/{repo_name}/releases/generate-notes",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_token}",
        },
        json=request,
    )
    if not response.status_code == 200:
        print(
            "Received status code {response.status_code} from GitHub API:",
            file=sys.stderr,
        )
        print(response.json(), file=sys.stderr)
        exit(1)

    release_notes = response.json()["body"]
    # print(release_notes)
    # Drop the generated by section
    release_notes = "\n".join(release_notes.splitlines()[2:])

    # Add newlines before all categories
    release_notes = release_notes.replace("\n###", "\n\n###")

    # Update what's new to release name
    release_notes = release_notes.replace("## What's Changed", f"## Release {tag_name}")

    # Parse all entries
    entries = ENTRY_REGEX.findall(release_notes)

    # Generate a contributors section
    contributors = ""
    for contributor in sorted(set(user for _, user, _ in entries)):
        contributors += f"\n- @{contributor}"

    # Replace the heading of the existing contributors section; append contributors
    release_notes = release_notes.replace(
        "## New Contributors", "### Contributors" + contributors
    )

    # Strip contributors from individual entries
    release_notes = ENTRY_REGEX.sub(
        lambda match: f"- {match[0]} — {match[2]}", release_notes
    )

    print(release_notes)




def extract_jira_ticket_no(pr_body):
    # Regular expression to match Jira ticket numbers
    jira_ticket_section = re.compile(r"### Ticket")
    # Splitting the PR body by lines
    lines = pr_body.splitlines()
    for i, line in enumerate(lines):
        section_match = jira_ticket_section.match(line)
        if jira_ticket_section:
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
                merged_prs.append({"title": pr['title'], "release_notes": extract_changelog(pr['body']),
                                   "ticket_no": extract_jira_ticket_no(pr['body'])})

        page += 1

    return merged_prs


if __name__ == "__main__":
    release = get_release_by_tag(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TAG)
    if release:
        release_id = release["id"]

        # Update the release (update name and body, set to draft or prerelease if needed)
        update_release(
            release_id,
            new_name="Updated Release Title",  # Optional: new release title
            new_body="Updated release description",  # Optional: new release body
            draft=False,  # Set to True if you want to make it a draft release
            prerelease=False  # Set to True if you want to mark it as a prerelease
        )
