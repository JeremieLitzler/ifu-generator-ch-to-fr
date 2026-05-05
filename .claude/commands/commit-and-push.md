Stage all changes, create a commit, and push to the remote.

Steps:

1. Run `rtk git status` to see what will be staged.
2. Run `rtk git diff` to review unstaged changes.
3. Run `rtk git log -5` to see recent commit messages and match the style.
4. Stage relevant files (prefer named files over `git add -A` to avoid committing secrets or large binaries).
5. Draft a concise commit message focused on the _why_, not the _what_. Use a HEREDOC so formatting is preserved. End the message with:
   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
6. Commit with `rtk git commit`.
7. Push with `rtk git push`.
8. Report the commit hash and confirm the push succeeded.
