#!/bin/bash

echo "Starting repository cloning..."
echo "--------------------------------"

repos=(
# "https://github.com/fastapi/typer.git"
# "https://github.com/encode/httpx.git"
# "https://github.com/encode/starlette.git"
# "https://github.com/python-pendulum/pendulum.git"
# "https://github.com/Textualize/rich.git"
# "https://github.com/PyCQA/bandit.git"
# "https://github.com/rubik/radon.git"
# "https://github.com/PyCQA/isort.git"
# "https://github.com/mkdocs/mkdocs.git"
# "https://github.com/cookiecutter/cookiecutter.git"
# "https://github.com/PyCQA/flake8.git"
# "https://github.com/hhatto/autopep8.git"
# "https://github.com/google/yapf.git"
# "https://github.com/pyupio/safety.git"
# "https://github.com/pyeve/cerberus.git"
# "https://github.com/arrow-py/arrow.git"
# "https://github.com/seperman/deepdiff.git"
# "https://github.com/Delgan/loguru.git"
# "https://github.com/dynaconf/dynaconf.git"
# "https://github.com/schemathesis/schemathesis.git"
# "https://github.com/pudo/dataset.git"
# "https://github.com/joerick/pyinstrument.git"
# "https://github.com/gruns/icecream.git"
# "https://github.com/HBNetwork/python-decouple.git"
# "https://github.com/kazhala/InquirerPy.git"

# -----------------------------
# HEALTHY (3)
# -----------------------------
"https://github.com/pallets/click.git"
"https://github.com/tox-dev/tox.git"
"https://github.com/python-jsonschema/jsonschema.git"

# -----------------------------
# STABLE (9)
# -----------------------------
"https://github.com/PyCQA/mccabe.git"
"https://github.com/PyCQA/pydocstyle.git"
"https://github.com/pallets/blinker.git"
"https://github.com/pallets/itsdangerous.git"
"https://github.com/python-attrs/attrs.git"
"https://github.com/pytest-dev/pluggy.git"
"https://github.com/pytest-dev/iniconfig.git"
"https://github.com/python/importlib_resources.git"
"https://github.com/python/importlib_metadata.git"

# -----------------------------
# NEEDS ATTENTION (13)
# -----------------------------
"https://github.com/rholder/retrying.git"
"https://github.com/Pylons/webob.git"
"https://github.com/Pylons/waitress.git"
"https://github.com/Pylons/hupper.git"
"https://github.com/Pylons/venusian.git"
"https://github.com/Pylons/translationstring.git"
"https://github.com/Pylons/webtest.git"
"https://github.com/Pylons/repoze.lru.git"
"https://github.com/Pylons/deform.git"
"https://github.com/Pylons/pyramid_tm.git"
"https://github.com/Pylons/pyramid_retry.git"
"https://github.com/Pylons/substanced.git"
"https://github.com/pyca/asn1crypto.git"
)

for repo in "${repos[@]}"; do
    echo "Cloning $repo..."
    git clone "$repo"
done

echo ""
echo "=========================================="
echo "All repositories have been processed."
echo "=========================================="