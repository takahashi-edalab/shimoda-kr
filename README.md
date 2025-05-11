# shimoda-kr

## Preliminary
- [pyenv](https://github.com/pyenv/pyenv)
- [poetry](https://github.com/python-poetry/poetry)


### Python Instal
```
pyenv install 3.10.11
```

## Build Environment
1. clone project repository
```
git clone git@github.com:takahashi-edalab/shimoda-kr.git kr
```
2. In the directory, create virtual python environment
```
cd kr
pyenv local 3.10.11
```

3. install necessary libraries to virtual environment
```
poetry config virtualenvs.in-project true && poetry install
```

## How to run
```
poetry run python -m src.main -a ccap -l D1
```
