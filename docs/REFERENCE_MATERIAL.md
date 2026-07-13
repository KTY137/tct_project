# Local Reference Material

This repository keeps the TCT application, project docs, agent setup, and owned
source files in Git. Third-party SDKs, manuals, lab photos, old checkout bundles,
and other IP-sensitive reference material stay local-only.

Ignored local folders:

| Path | Purpose |
|---|---|
| `reference/` | Third-party or historical source checkouts used for reading protocol and driver examples |
| `lab_assets/` | Lab photos, source PDFs, manuals, and other binary reference files |
| `sources/git_history/` | Recovery bundles for the old nested Git repositories |

Do not commit files from these folders unless ownership and redistribution rights
are clear. If a code path depends on local reference material, keep that
dependency optional and preserve simulation/test behavior without it.

The full pre-cleanup import is preserved locally on
`backup/full-import-with-reference` for recovery. Do not push that branch unless
the reference material has been reviewed for redistribution.
