# Sample tracker

Tiny Python library used by the harness demo.

`classify_priority` is supposed to map impact and urgency onto `high`,
`medium`, or `low`. The implementation currently disagrees with the tests.

```bash
python3 -m pytest test_tracker.py -q
```
