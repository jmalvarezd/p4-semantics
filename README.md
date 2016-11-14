# P4K: Formal Semantics of P4 in K

This is an ongoing attempt to give formal semantics to  [P4](http://p4.org/) language using K framework.

## Using P4K:

At the current moment, only the parser part is ready, which converts p4 source code into KAST (K's AST).

### Dependencies:
- JRE 8
- K Framework
  + make sure the executables (kompile, kast, krun) are on PATH.
- GCC
  + only needed for preprocessing p4 source files

### Building the parser

You first need to compile (kompile) the P4 language definition using K. In order to do so run:
```
  cd p4k/
  scripts/kompile-syntax.sh
```

### Using the parser

In order to parse P4 programs run:

```
  scripts/parse.sh path/to/source.p4
```

If your code contains preprocessing directives (e.g include, define, etc), you first need to preprocess it:
```
  scripts/preproc.sh path/to/source.p4 > some_file.p4
```

And then feed the output file into the parser.


### Examples

```
  scripts/parse.sh test/syntax/unit/mtag-edge-program.p4
  `'P4Declarations`(`header_type_{_}`(#token("ethernet_t","Id@ID"),...
```

### Questions/Problems?

Contact [Ali Kheradmand](kheradm2@illinois.edu) 