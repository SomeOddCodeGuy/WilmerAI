---
name: Git Author Setup
type: knowledge
version: 1.0.0
agent: CodeActAgent
triggers:
  - "git author setup"
  - "set git author"
  - "configure git committer"
---

# Git Author Setup Microagent

This microagent helps set up the Git author and committer information for Anton Sokolchenko.

## Usage

When a user requests to set up or change the Git author/committer information, use this microagent to guide you through the process. The preferred configuration is:

- Name: "Anton Sokolchenko"
- Email: "wsevendays@gmail.com"

## Commands

To configure the Git author and committer globally:
```bash
git config --global user.name "Anton Sokolchenko"
git config --global user.email "wsevendays@gmail.com"
```

To set up for a specific repository (not global):
```bash
git config user.name "Anton Sokolchenko"
git config user.email "wsevendays@gmail.com"
```

## Example Scenarios

1. **Setting up Git author globally:**
   - User: "I need to configure my Git author information."
   - Assistant: "Sure, I'll set the Git author and committer to Anton Sokolchenko globally."

2. **Changing commit author for a specific commit:**
   - User: "Can you change the author of the last commit?"
   - Assistant: "Certainly, I'll amend the last commit with the correct author information."

3. **Fixing already pushed commit with wrong committer:**
   - User: "I need to fix a pushed commit that has the wrong committer information."
   - Assistant:
     1. Reset the last commit: `git reset --soft HEAD~1`
     2. Create a new commit with correct author: `git commit --allow-empty -m "Fix commit author" --author="Anton Sokolchenko <wsevendays@gmail.com>"`
     3. Force push to update the remote repository: `git push --force origin branch-name`

     
## Limitations

- This microagent only handles setting up Git author and committer information.
- It doesn't handle complex scenarios like changing authors for multiple commits or in a specific branch.

## Error Handling

If you encounter issues with Git configuration:
1. Check if there are existing configurations that might be conflicting
2. Verify the user has permission to change Git settings
3. Ensure the correct scope (global vs repository-specific) is used based on the context