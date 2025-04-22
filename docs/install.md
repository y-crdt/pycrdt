Pycrdt can be installed through [PyPI](https://pypi.org) or [conda-forge](https://conda-forge.org).

## With `pip`

```bash
pip install pycrdt
```

## With `micromamba`

We recommend using `micromamba` to manage `conda-forge` environments (see `micromamba`'s
[installation instructions](https://mamba.readthedocs.io/en/latest/installation.html#micromamba)).
First create an environment, here called `my_env`, and activate it:
```bash
micromamba create -n my_env
micromamba activate my_env
```
Then install `pycrdt`.

```bash
micromamba install -c conda-forge pycrdt
```

## Development install

You first need to clone the repository:
```bash
git clone https://github.com/y-crdt/pycrdt.git
cd pycrdt
```
We recommend working in a conda environment. In order to build `pycrdt`, you will need
`pip` and the Rust compiler:
```bash
micromamba create -n pycrdt-dev
micromamba activate pycrdt-dev
micromamba install -c conda-forge pip rust
```
Then install `pycrdt` in editable mode:
```bash
pip install -e .
```
This will build the Rust extension using [maturin](https://www.maturin.rs). If you make changes
to the Python code only, you don't need to recompile anything, changes will be reflected the next
time you run the Python interpreter. If you make changes to the Rust code, you need to recompile it
but you don't need to reinstall `pycrdt`, you can just re-build the Rust extension with:
```bash
# install maturin only once:
pip install maturin
# build the Rust extension each time the Rust code changes:
maturin develop
```
