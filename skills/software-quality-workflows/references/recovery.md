# Conflict and repository recovery

Read only for an actual conflict or damaged/interrupted repository operation.

Inspect current operation, affected refs/index/worktree and relevant local changes before repair. Preserve irreplaceable and unrelated work. Establish the intended result from the competing changes and their callers; do not resolve a conflict by blindly choosing one side.

For repository damage, identify the exact broken invariant. Prefer current objects, operation metadata and reflogs, then known backups or reproducible inputs. Distinguish exact recovery from reconstruction and missing data. Choose the least destructive action within the requested scope; unavailable evidence does not justify inventing content or broad cleanup.

After repair, check the affected state and nearest behavior. Report any remaining loss or unavailable verification. Do not reset, clean, rewrite history or delete user state merely to make status look clean.
