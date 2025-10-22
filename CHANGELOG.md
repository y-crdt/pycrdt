# Version history

## 0.12.42

- Bump `pyo3` to v0.27.1.

## 0.12.41

- Bump `pyo3` to v0.27.0.
- Drop PyPy 3.10 support.

## 0.12.40

- Support Python v3.14.

## 0.12.38

- Improve error propagation with `PyResult`.
- Cleanup transaction when commit fails.

## 0.12.37

- Drop Python 3.9 support.
- Drop dependency on `importlib_metadata`.
- Support async callbacks in `observe_subdocs`.
- Allow iterating over a document events by registering async callbacks when async transactions are used.

## 0.12.36

- Support document change async callbacks.
- Allow `get_state` and `get_update` to use an existing transaction.

## 0.12.35

- Bump `trio` to <0.32.

## 0.12.34

- Add snapshot support.
- Install multiple Pythons to not rely on Windows hosted Python cache.

## 0.12.32

- Fix `skip_gc` in `Doc`.

## 0.12.31

- Expose `skip_gc` in `Doc`.

## 0.12.30

- Allow turning garbage collection off.

## 0.12.29

- Improve performance of `map.__contains__`.

## 0.12.28

- Upgrade `pyo3` to v0.26.0.

## 0.12.27

- Support XML `insert_embed` shared types.
- Fix `UndoManager` with `XmlFragment`.

## 0.12.26

- Bump `trio` to <0.31.

## 0.12.25

- Allow XML attributes to be of any type.

## 0.12.24

- Upgrade `yrs` to v0.24.0.

## 0.12.23

- Support sticky index.

## 0.12.22

- Upgrade `yrs` to v0.23.5.

## 0.12.21

- Upgrade `pyo3` to v0.25.1.

## 0.12.20

- Upgrade `yrs` to v0.23.4.

## 0.12.19

- Upgrade `yrs` to v0.23.3.

## 0.12.18

- Upgrade `yrs` to v0.23.2.

## 0.12.17

- Upgrade `pyo3` to v0.25.0.

## 0.12.16

- Add `Provider` and `Channel`.

## 0.12.15

- Upgrade `pyo3` to v0.24.2.

## 0.12.14

- Upgrade `yrs` to v0.23.1.

## 0.12.13

- Add `is_awareness_disconnect_message()`.
- Close memory streams in event iterators.

## 0.12.12

- Add doc and shared type `events()` async event iterator.
- Fix deadlock while getting root type from within transaction.

## 0.12.11

- Upgrade `pyo3` to v0.24.1.

## 0.12.10

- Upgrade `yrs` to v0.23.0.
- Pin `trio <0.30.0` in tests.

## 0.12.9

- Upgrade `pyo3` to v0.24.0.

## 0.12.8

- Bump trio upper version to <0.29.

## 0.12.7

- Add `pycrdt.__version__`.
- Use PyPI's trusted publishing.

## 0.12.4

- Upgrade `yrs` to v0.22.0.

## 0.12.3

- Upgrade `pyo3` to v0.23.4.

## 0.12.2

- Allow passing a Python timestamp function to an undo manager.

## 0.12.1

- Add `TypedArray` typed container.

## 0.12.0

- Add `TypedDoc` and `TypedMap` typed containers.

## 0.11.1

- Rearrange typing tests and docs.

## 0.11.0

- Drop Python v3.8.
- Support type annotations.

## 0.10.9

- Bump `pyo3` to v0.23.3.

## 0.10.8

- Fix `Array` iterator.

## 0.10.7

- Add support for adding `XmlFragments` to arrays and maps (PR by @ColonelThirtyTwo).

## 0.10.6

- Bump yrs v0.21.3 and pyo3 v0.22.5.

## 0.10.4

- Add `CHANGELOG.md` and automate release on tag.
- Add support for XML, Text attributes and embeds (#184) (PR by @ColonelThirtyTwo).

## 0.10.3
