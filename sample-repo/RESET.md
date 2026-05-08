# Resetting The Sample Repo

The checked-in sample repo is intentionally broken. DevPilot copies it into `runtime/workspaces/incident-*` before repairing, so repeated judging runs do not mutate this original folder.

Expected initial failures:

- `app/math_tools.py` imports `normalize_number`, but only `normalize_value` exists.
- `app/api.py` returns the wrong greeting contract.
- `app/api.py` accepts users without an email.

Run the sample tests manually:

```powershell
cd sample-repo
python -m pytest
```
