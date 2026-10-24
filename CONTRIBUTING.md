# Contributing to MarketMyna

Thanks for helping. Bug reports, ideas and pull requests are welcome on
[GitHub](https://github.com/pryndor/MarketMyna).

## Before you open a pull request

- Run the tests: `python -m pytest -q`, and `npx tsc -b --noEmit` in `frontend/`.
- Keep changes focused, and match the style of the code around them.
- Don't include API keys, tokens, `.env` files or personal data.

## Releasing (maintainers)

The package is published to [PyPI](https://pypi.org/project/marketmyna/) by
`.github/workflows/publish.yml` (trusted publishing, no token stored):

1. Set the new version in `pyproject.toml` and `marketmyna/__init__.py`
   (`tests/test_packaging.py` checks they match).
2. Push the change, then a matching tag: `git tag v0.2.1 && git push origin v0.2.1`.
3. The workflow builds the frontend into the package, installs and starts it,
   uploads it to PyPI and creates the GitHub release.

A version can be uploaded to PyPI only once, so every fix needs a new version.
Build locally with `pip install build && python .github/build_package.py`.

## License of contributions

MarketMyna is released under the [Apache License 2.0](LICENSE). By opening a
pull request you confirm that the contribution is your own work, or that you
have the right to submit it, and that it is licensed under the Apache License 2.0
(section 5 of the license). You keep the copyright of your contribution.
