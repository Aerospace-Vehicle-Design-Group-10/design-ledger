

### Goal
Okay, goal of this library is going to be the tracking of data and its provenance.

I'm thinking we can use a sort of `get("...")` and `publish("...")` syntax.

We can track what was imported from the global state through `get`, and we can save to global state with `publish`


### Global state
Global state should be several JSON's (probably one per general area like `weights`, `wing`, `aero`, same split as in the coursework brief):
*this is probably going to get changed later just because this is an initial idea*
```json
"variable_name": {
    "value": ..., // numerical value
    "units": ..., 
    "owner": ..., // the general area (eg. weights)
    "source": ..., // we can give it the file name/and append a stripped hash of the file 

    "inputs": { // all variables received through "get" 
        "input_i": ..., // this will most definitely false flag but rather that than not tracking
        ...
    },
    "updated": ..., // just the date
    "by": ..., //whoever committed the change 
}

```

### Usage
So, eg, we could do something like this

```python
import ledger

W0 = ledger.get("MTOW")
...
x_cg = ...
ledger.publish("CG_x", x_cg, units = "m")
```

`publish` should only write to the local copy of the repo. The numbers can then become global once committed and merged into main (use pull requests prob).

What we can do is that if eg `CG_x` was computed with an `MTOW` (which is listed in the inputs) that isn't the same as what `MTOW` currently is, it can then flag that in the pull request (i'll just set up a CI job for that)

Convenience commands for the terminal like eg `ledger push` which can create a new branch and the pull request so that it can be approved and merged




