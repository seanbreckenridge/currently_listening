# currently_listening_py

Local server module for [mpv_history_daemon](https://github.com/seanbreckenridge/mpv-history-daemon)

This runs on my local machine, connecting to active `mpv` sockets at `/tmp/mpvsockets/`, filtering using the login in [my_feed](https://github.com/seanbreckenridge/my_feed/blob/master/src/my_feed/sources/mpv.py) relaying the information to the remote server

## Installation

Requires `python3.8+`

## Usage

```
currently_listening_py --help
```

### Tests

```bash
git clone 'https://github.com/seanbreckenridge/currently_listening_py'
cd ./currently_listening_py
pip install '.[testing]'
flake8 ./currently_listening_py
mypy ./currently_listening_py
```
