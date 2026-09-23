# Fantazy Labz — Org Chart (Graph View)

Two renderings of the same reporting hierarchy (12 people): a Mermaid diagram
(renders on GitHub / Mermaid Live) and a plain-text tree.

## Mermaid diagram

```mermaid
graph TD
    P1["Elena Marchetti<br/>Chief Executive Officer"]
    P2["Rajesh Kapoor<br/>Chief Technology Officer"]
    P3["Sofia Reyes<br/>Chief Financial Officer"]
    P4["Marcus Bergström<br/>Chief Operating Officer"]
    P7["Yuki Tanaka<br/>Chief Information Security Officer"]
    P11["Gregory Whitfield<br/>Director of Finance"]
    P12["Fatima El-Sayed<br/>Director of Operations & IT"]
    P16["Hannah Fischer<br/>Director of People Operations"]
    P24["Samuel Adeyemi<br/>Accounting Manager"]
    P25["Natalia Popov<br/>IT Manager"]
    P40["Rebecca Stern<br/>Staff Accountant"]
    P41["Bruno Costa<br/>IT Support Specialist"]
    P1 --> P2
    P1 --> P3
    P1 --> P4
    P1 --> P7
    P3 --> P11
    P4 --> P12
    P11 --> P24
    P12 --> P25
    P24 --> P40
    P25 --> P41
```

## Text tree

```
Elena Marchetti (CEO, Executive)                       [level 1]
├── Rajesh Kapoor (CTO, Engineering)                   [level 2]
├── Sofia Reyes (CFO, Finance)                         [level 2]
│   └── Gregory Whitfield (Director of Finance)        [level 3]
│       └── Samuel Adeyemi (Accounting Manager)        [level 4]
│           └── Rebecca Stern (Staff Accountant)       [level 5]
├── Marcus Bergström (COO, Operations)                 [level 2]
│   └── Fatima El-Sayed (Director of Operations & IT)  [level 3]
│       └── Natalia Popov (IT Manager)                 [level 4]
│           └── Bruno Costa (IT Support Specialist)    [level 5]
├── Yuki Tanaka (CISO, Security)                       [level 2]
└── Hannah Fischer (Director of People Operations, HR) [level 3]
```
