# Syntax — implementation contract

> This file is an implementation contract derived from V3.
> It has no authority over V3.
> If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
Braces (6.1, 7.1.1); newline-terminated statements with defined continuation rules
and clear diagnostics (7.1.2); keyword priors (7.1.3); postfix return annotation
(7.1.4, 4.4); brace interpolation (7.1.5); lambda family (7.1.6); consequential
distinctions explicit (4.5: `use` vs `let`, `record` vs `mutable record`, throwing
vs non-throwing); searchable failure markers (`try`, 4.7); canonical formatter (4.8).

## 2. Lexical grammar
- Identifiers `[A-Za-z_][A-Za-z0-9_]*`. Keywords after `.` are ordinary member names.
- Hard keywords: `fn async await let const return if else while for in break
  continue match mutable throws throw try catch capture propagate as is use yield
  borrow defer parallel spawn select within import pub assert true false null
  nonlocal self`.
- Contextual keywords (keyword only in the stated position): `record enum error
  category protocol predicate test resource` (top-level declaration start);
  `requires ensures` (function header); `invariant sensitive satisfies yields`
  (declaration bodies/headers); `collect race firstSuccess` (after `parallel`);
  `now priority` (after `select`); `receive send from to task completed at after
  when closed none ready` (inside select); `onAbandon` (statement start); `old`
  and `result` (inside contracts; `result` is otherwise an ordinary identifier).
- Numbers: `123`, `1_000`, `0x1F`, `0b101`, `1.5`, `1e9`, `2.5e-3`. `5.seconds`
  lexes as Int `5`, `.`, `seconds` (a digit must follow `.` for a Float).
- Strings: `"..."` single-line, `"""..."""` multi-line. Escapes `\n \t \r \0 \\ \"
  \{ \} \u{HEX}`. Interpolation `{expr}` or `{expr:spec}`; spec `[<>]?width?(.prec)?`.
- Comments `// ...` and `/* ... */`; retained as trivia for the formatter.
- NEWLINE tokens are emitted for every line break outside strings/comments;
  the *parser* decides continuation (contexts below).

## 3. Grammar (EBNF; `NL` = newline token)
```
module     = { NL | import | decl } EOF
import     = "import" path [ "." "{" name {"," name} "}" ] [ "as" name ]
decl       = ["pub"] ( fn_decl | record_decl | enum_decl | error_decl | category_decl
                     | protocol_decl | predicate_decl | const_decl ) | test_decl
fn_decl    = ["async"] ["resource"] "fn" name [type_params] "(" params ")"
             [ "->" type | "yields" type ] [ "throws" throws_list ]
             { "requires" expr | "ensures" expr } block
type_params= "[" name {"," name} "]"
params     = [ param {"," param} [","] ]
param      = "self" | name [":" ["borrow"] type] ["=" expr]
throws_list= type { ("," | "|") type }
record_decl= ["mutable"] "record" name [type_params] ["satisfies" type {"," type}]
             "{" { (field | "invariant" expr | ["pub"] fn_decl) (NL | ",") | NL } "}"
field      = ["sensitive"] name ":" type ["=" expr]
enum_decl  = "enum" name [type_params] ["satisfies" ...] "{" { (case | fn_decl) (NL | ",") | NL } "}"
case       = name [ "(" field_sig {"," field_sig} ")" ]       field_sig = name ":" type
error_decl = "error" name ["category" name] [ "{" { field | fn_decl | NL } "}" ]
           | "error" "enum" name ["category" name] "{" { case | NL } "}"
category_decl = "category" name
protocol_decl = "protocol" name [type_params] "{" { proto_fn | NL } "}"
proto_fn   = ["async"] "fn" name "(" params ")" ["->" type] ["throws" throws_list]
             { "requires" expr | "ensures" expr }
predicate_decl = "predicate" name "(" params ")" block
const_decl = "const" name [":" type] "=" expr
test_decl  = "test" STRING block

block      = "{" { stmt (NL | ";") } "}"
stmt       = "let" bind_target [":" type] ["=" expr] | "const" name [":" type] "=" expr
           | "return" [expr] | "break" | "continue" | "throw" expr
           | "defer" (block | expr) | "onAbandon" expr | "nonlocal" name {"," name}
           | "assert" expr ["," expr] | "while" cond block
           | "for" ["await"] pattern "in" expr block
           | target assign_op expr | expr
bind_target= name | "(" name {"," name} ")"
assign_op  = "=" | "+=" | "-=" | "*=" | "/=" | "%="
cond       = expr            (an `is` pattern inside may bind names for the block)

expr       = "try" expr { "catch" catch_clause } [ "else" expr ]
           | "capture" expr | "yield" expr | or_expr
catch_clause = ["category"] qualified ["as" name] "=>" (block | expr)
or_expr    = and_expr { "||" and_expr }
and_expr   = cmp_expr { "&&" cmp_expr }
cmp_expr   = rel_expr [ ("==" | "!=") rel_expr ]
rel_expr   = is_expr [ ("<" | "<=" | ">" | ">=") is_expr ]
is_expr    = range_expr [ "is" pattern ] [ "as" type ]
range_expr = add_expr [ (".." | "..=") add_expr ]
add_expr   = mul_expr { ("+" | "-") mul_expr }
mul_expr   = unary { ("*" | "/" | "%") unary }
unary      = ("-" | "!") unary | "await" unary | "propagate" unary | postfix
postfix    = primary { "(" args ")" | "[" expr {"," expr} "]" | "." (name | INT)
                     | "with" "{" field_init {"," field_init} "}" }
args       = [ arg {"," arg} [","] ]     arg = [name ":"] expr
primary    = literal | name | "self" | "(" expr ")" | "(" expr "," ... ")"
           | "[" [expr {"," expr}] "]" | "{" [expr ":" expr {"," ...}] "}"
           | lambda | if_expr | match_expr | use_expr | parallel_expr | spawn_expr
           | select_expr | within_expr
lambda     = ["async"] "fn" "(" params ")" ["->" type] ["throws" throws_list]
             ( "=>" expr | block )
if_expr    = "if" cond block [ "else" (if_expr | block) ]
match_expr = "match" expr "{" { pattern ["if" expr] "=>" (block | expr) (NL | ",") } "}"
use_expr   = "use" name "=" expr block
parallel_expr = "parallel" ["collect" | "race" | "firstSuccess"] block
spawn_expr = "spawn" (block | postfix-call)
within_expr= "within" expr block
select_expr= "select" ["now" | "priority"] "{" { branch (NL | ",") } "}"
branch     = ["when" name ":"] ( "receive" (name|"_") "from" expr
           | "closed" expr | "send" expr "to" expr
           | "task" expr "completed" "as" name | "at" expr | "after" expr )
             "=>" (block | expr)
           | "none" "ready" "=>" (block | expr)

pattern    = alt_pattern { "|" alt_pattern }
alt_pattern= "_" | literal | "-" number | name [":" type]
           | qualified [ "(" [subpat {"," subpat}] ")" ]   (variant/record/core case)
           | "(" pattern "," pattern {"," pattern} ")"
subpat     = [name ":"] pattern
type       = base { "?" }
base       = qualified [ "[" type {"," type} "]" ] | "(" type "," type {"," type} ")"
           | ["async"] "fn" "(" [type {"," type}] ")" ["->" type] ["throws" type {"|" type}]
```

## 4. Continuation contexts (parser-driven)
Newlines are skipped: inside `()`/`[]` and map literals (until the matching close,
except inside nested blocks); after any binary operator, `,`, `=`, `=>`, `->`,
`:` (types); before a line starting with `.` (method chain); before `else`/`catch`;
in a function header before `throws`/`requires`/`ensures`/`yields`/`{`. A statement
beginning with a binary operator token other than `-`/`!` produces
`S.SYNTAX.LEADING_OPERATOR` with a suggested edit moving the operator up.

## 5. Recovery
Statement-level synchronisation: on error skip to the next NL at the current brace
depth or to a closing `}`; declaration-level: skip to the next line beginning with a
declaration keyword at depth 0. Errors after the first one in the same statement are
suppressed; errors produced while recovering from an unclosed delimiter are marked
`likely_cascade` with a note pointing at the root error.

## 6. Conformance examples
See `tests/unit/test_lexer.py`, `tests/unit/test_parser.py`,
`tests/negative/test_syntax_errors.py`.
