# GitHub Actions security settings

The CI uses standard GitHub-hosted Ubuntu runners. It does not need repository
secrets, cloud credentials, deployment permissions, or self-hosted runners.

## Workflow controls

- Actions are pinned to full commit SHAs; uv is pinned to a release version.
- Token permissions are denied by default. The check job only receives
  `contents: read` to check out the repository.
- Checkout does not persist Git credentials for subsequent build or test steps.
- Dependency caching is disabled. No artifacts are uploaded.
- Each job has a 15-minute timeout. New commits cancel older runs for the same ref.
- CI runs on pushes to `main` and pull requests targeting `main` using
  `pull_request`. Do not switch PR testing to `pull_request_target` or a privileged
  `workflow_run` workflow.
- Dependabot proposes weekly updates to action pins. Review these changes;
  automatic merging is not configured. Update the pinned uv release separately.

## Repository settings to apply on GitHub

These settings cannot be enforced by the workflow file. A repository admin must
apply them under **Settings > Actions > General**:

1. Under **Actions permissions**, allow only this owner and selected non-owner
   actions. Disable the broad GitHub-created and verified-Marketplace allowances.
   Add only `actions/checkout@*` and `astral-sh/setup-uv@*` to the allowlist.
2. Enable **Require actions to be pinned to a full-length commit SHA**. The `@*`
   entries above allow SHA updates; this policy still requires immutable pins.
3. Under fork workflow approval, select **Require approval for all external
   contributors**. Before approving, inspect workflow changes, dependency changes,
   build hooks, and tests: all can execute code on the runner.
4. Under **Workflow permissions**, choose **Read repository contents and packages
   permissions**. Leave **Allow GitHub Actions to create and approve pull requests**
   disabled. The workflow further limits its own token to repository read access.
5. Do not enable sending write tokens or secrets to fork PR workflows if those
   settings are available. Do not attach self-hosted runners to this public CI.
6. Set log and artifact retention to 14 days. This workflow does not upload build
   artifacts and does not use a shared Actions cache.

For `main`, use a branch ruleset to require pull requests, successful CI checks
(all nine `Python <version> / Core <version>` checks listed in the README), block force pushes, and block branch deletion.
After the first successful run, select the actual check names in the ruleset UI.
If another trusted maintainer is available, also require their review for workflow
and dependency changes. A solo maintainer cannot approve their own pull request.

Workflow approval permits execution of submitted code; it does not certify that
code as safe. SHA pins and lockfiles reduce unexpected dependency changes but do
not eliminate dependency risk or restrict network access from a hosted runner.
Keep credentials out of this CI and review dependency and workflow updates.

## Billing

Standard GitHub-hosted runner execution is free for public repositories. Private
repositories have plan-dependent quotas; larger runners are charged even for
public repositories. Storage has separate allowances. This workflow avoids cache
storage and artifact uploads. To prevent private-repository overage, configure an
Actions budget with **Stop usage when budget limit is reached** in account billing.

## Official references

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Repository Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)
