# Contributing

selecont is currently founder-led and focused on validating one product hypothesis. Small, well-tested changes are welcome; large feature additions should begin with an issue that explains the user problem and the access implications.

## Development setup

```bash
sh apps/api/scripts/start-demo.sh
```

## Before opening a pull request

Run the complete local checks:

```bash
apps/api/.venv/bin/python -m unittest discover -s apps/api/tests -v
apps/api/.venv/bin/python -m pip check
```

Changes to authorization, circles, posts, comments or media must include a negative test showing that an unauthorized viewer cannot access the resource. Preserve the core invariants documented in [docs/PRODUCT-SPEC.md](docs/PRODUCT-SPEC.md).

Keep generated databases, media, environment files and personal data out of commits. The project does not currently grant a reuse license; a contribution does not change that status.
