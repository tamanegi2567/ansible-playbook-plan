# ansible-playbook-plan

[![CI](https://github.com/tamanegi2567/ansible-playbook-plan/actions/workflows/ci.yml/badge.svg)](https://github.com/tamanegi2567/ansible-playbook-plan/actions/workflows/ci.yml)

`ansible-playbook-plan` shows the resolved host order, serial batches, and
task-level execution details for Ansible playbooks without connecting to hosts
or running tasks.

Use it to preview how Ansible will divide a rollout before running
`ansible-playbook`. The plan includes:

- the hosts selected by the inventory, play pattern, and `--limit`;
- the resolved host order and `serial` batches;
- the initial fork slots and hosts waiting in the dispatch queue; and
- task details such as `run_once`, `when`, `throttle`, and `delegate_to`.

## Installation

Run directly from the Git repository with `uvx`:

```sh
uvx --python 3.14 --from git+https://github.com/tamanegi2567/ansible-playbook-plan.git \
  ansible-playbook-plan --help
```

Alternatively, install it with `pipx`:

```sh
pipx install --python python3.14 git+https://github.com/tamanegi2567/ansible-playbook-plan.git
```

Python 3.14 with Ansible Core 2.21 is recommended. Supported combinations:

| Python | Ansible Core |
| --- | --- |
| 3.11 | 2.19 |
| 3.12 / 3.13 | 2.19 / 2.20 / 2.21 |
| 3.14 | 2.20 / 2.21 |

The explicit Python option keeps tools from using an unsupported interpreter.
For `pipx`, install Python 3.14 first and ensure `python3.14` is on your `PATH`.

### Support policy

We target release series receiving upstream security updates and recommend the
latest patch release in each series. Python 3.11 and Ansible Core 2.19 remain
supported during this transition. When Core 2.19 reaches its scheduled end of
life in November 2026, a separate update will raise the minimum versions to
Python 3.12 and Core 2.20.

See the [Python lifecycle](https://devguide.python.org/versions/) and
[Ansible Core support matrix](https://docs.ansible.com/projects/ansible-core/devel/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix).

If `uvx` cached an older Git revision, add `--refresh` to the command to fetch
the updated package. uv can ignore package Python upper bounds during tool
resolution, so this command explicitly selects Python 3.14.

## Quick start

The [`samples`](samples) directory contains an inventory and a safe playbook
whose tasks only use `ansible.builtin.debug`. Preview it from the repository:

```sh
uv run ansible-playbook-plan \
  -i samples/inventory.yml \
  --forks 1 \
  -e rollout_serial=2 \
  samples/rolling-update.yml
```

The most relevant parts of the output are:

```text
play #1 (application_servers): Preview a rolling application update
  order: sorted
  serial: 2
  forks: 1
  hosts (4), serial batches (2):
    serial batch 1 (2 hosts):
      initial fork slots (1 used of 1):
        fork 1: 1. app-01
      dispatch queue (1 host; starts as fork slots become available):
        2. app-02
    serial batch 2 (2 hosts):
      initial fork slots (1 used of 1):
        fork 1: 3. app-03
      dispatch queue (1 host; starts as fork slots become available):
        4. app-04
  tasks (2):
    1. Check each batch once
      execution: first host in each serial batch
        batch 1: app-01
        batch 2: app-03
    2. Update each application server
      execution: all 4 play hosts, subject to runtime conditions
      throttle: 1
```

This means Ansible resolves the four hosts into two batches. With one fork,
the first host in each batch gets the initial slot and the second waits in the
dispatch queue. The first task has `run_once: true`, so it selects one host per
serial batch. The second task applies to every host, while `throttle: 1` limits
its runtime concurrency.

## Usage with your playbooks

Use the standard `ansible-playbook` inventory, limit, extra variable, vault,
check mode, diff mode, and forks options:

```sh
ansible-playbook-plan \
  -i inventories/production/hosts.yml \
  --limit application_servers \
  -e rollout_serial=2 \
  site.yml
```

### Planning behavior and limitations

- **Read-only operation:** The command rejects `--flush-cache` because that
  option clears cached facts. It does not connect to hosts or run tasks.
- **Concurrency:** The initial fork slot count is the upper bound imposed by
  the serial batch size and `forks`. Task-level throttles and runtime conditions
  can reduce the actual concurrency, and runtime completion order is not
  predicted.
- **`run_once`:** For a literal `run_once: true`, the selected host is shown
  for each serial batch.
- **Conditions:** Simple conditions based on command-line extra variables are
  evaluated without executing arbitrary expressions. Conditions that depend
  on facts or runtime results remain visible and unevaluated.
- **Dynamic includes:** The include task is shown, but the tasks it selects at
  runtime are not expanded.

## Continuous integration

[GitHub Actions](https://github.com/tamanegi2567/ansible-playbook-plan/actions/workflows/ci.yml)
runs for pull requests and pushes to `main`. All nine supported Python/Core
combinations run the tests in isolated tox environments, using the latest
available patch of the selected Core series from public PyPI. Each job also
checks the committed lockfile; it selects Core 2.19 on Python 3.11 and Core 2.21
on Python 3.12–3.14.
Python 3.14 / Core 2.21 also runs Ruff, builds the package, and smoke tests
the wheel in a separate environment.
See [Actions security settings](.github/ACTIONS_SECURITY.md) for workflow controls
and the repository settings to apply before accepting external contributions.

## Development

Install dependencies and run the checks with `uv`:

```sh
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked tox
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Run the local command without installing it globally:

```sh
uv run ansible-playbook-plan --help
```

## License

Released under the [MIT License](LICENSE).
