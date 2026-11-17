"""
Build a blank three-statement + DCF model, laid out the way an analyst's is.
===========================================================================

WHAT THIS IS FOR
----------------
A template to learn the structure on. Every formula is live, so typing an
assumption flows through the income statement, the balance sheet, the cash
flow statement and the DCF. Nothing is pre-filled with a company's numbers —
the point is to see how the pieces connect.

THE CONVENTIONS IT FOLLOWS
--------------------------
These are near-universal on a desk, and worth internalising because they are
how someone else reads your model:

    BLUE font   a hardcoded INPUT. You type it.
    BLACK font  a FORMULA. You never type over it.
    GREEN font  a link to another sheet.
    Red         a check that is failing.

If you see a blue number inside the income statement, something is wrong:
assumptions belong on the Assumptions tab and nowhere else. The discipline
sounds pedantic and it is the single thing that stops a model becoming
unauditable after a month away from it.

    A suffix   actual, reported
    E suffix   estimate, forecast

CHECKS
------
Two rows exist to catch the errors that matter:

    Balance check     assets minus liabilities and equity. Must be zero.
    Cash tie          closing cash on the balance sheet versus the cash
                      flow statement. Must be zero.

A three-statement model that does not tie is not a model. These are the first
things a reviewer looks at, before reading a single assumption.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# --- house style ------------------------------------------------------------
INPUT = Font(color="0000CC", name="Calibri", size=10)          # blue: you type
FORMULA = Font(color="000000", name="Calibri", size=10)        # black: computed
LINK = Font(color="007700", name="Calibri", size=10)           # green: cross-sheet
HEAD = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
SECTION = Font(bold=True, color="000000", name="Calibri", size=10)
TITLE = Font(bold=True, size=13, name="Calibri")
NOTE = Font(italic=True, size=9, color="666666", name="Calibri")

HEAD_FILL = PatternFill("solid", fgColor="1F3864")
SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")
CHECK_FILL = PatternFill("solid", fgColor="FFF2CC")

THIN = Side(style="thin", color="BFBFBF")
TOP_BORDER = Border(top=THIN)
MONEY = '#,##0;(#,##0)'
PCT = '0.0%'
MULT = '0.0"x"'
TWO = '#,##0.00;(#,##0.00)'

# Rows that other sheets must reference BEFORE those sheets are built. The
# layout is fixed by this script, so these are known -- but a forward
# reference guessed at produces a silent #REF!, which is why they are named
# constants with the sheet that owns them, rather than inline magic numbers.
BS_DEBT_ROW = 18          # BS "Total debt"
BS_CASH_ROW = 7           # BS "Cash and equivalents"
CF_NET_CHANGE_ROW = 26    # CF "Net change in cash"

# Three actual years then five estimates. B..D actual, E..I estimate.
YEARS = ["FY2023A", "FY2024A", "FY2025A", "FY2026E", "FY2027E",
         "FY2028E", "FY2029E", "FY2030E"]
FIRST = 2                     # column B
LAST = FIRST + len(YEARS) - 1  # column I
FIRST_EST = FIRST + 3          # column E
COLS = [get_column_letter(c) for c in range(FIRST, LAST + 1)]
EST = [get_column_letter(c) for c in range(FIRST_EST, LAST + 1)]


def header(ws, title: str, subtitle: str = "") -> int:
    ws["A1"] = title
    ws["A1"].font = TITLE
    if subtitle:
        ws["A2"] = subtitle
        ws["A2"].font = NOTE
    row = 4
    ws.cell(row, 1, "$ in millions unless noted").font = NOTE
    row += 1
    for i, label in enumerate(YEARS):
        cell = ws.cell(row, FIRST + i, label)
        cell.font = HEAD
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center")
    ws.cell(row, 1, "").fill = HEAD_FILL
    ws.column_dimensions["A"].width = 42
    for col in COLS:
        ws.column_dimensions[col].width = 12
    ws.freeze_panes = ws.cell(row + 1, FIRST)
    return row + 1


def section(ws, row: int, label: str) -> int:
    cell = ws.cell(row, 1, label)
    cell.font = SECTION
    cell.fill = SECTION_FILL
    for c in range(FIRST, LAST + 1):
        ws.cell(row, c).fill = SECTION_FILL
    return row + 1


def line(ws, row: int, label: str, formulas=None, fmt=MONEY,
         font=FORMULA, indent: int = 1, note: str = "") -> int:
    cell = ws.cell(row, 1, label)
    cell.alignment = Alignment(indent=indent)
    if formulas:
        for i, f in enumerate(formulas):
            c = ws.cell(row, FIRST + i, f)
            c.font = font
            c.number_format = fmt
    if note:
        ws.cell(row, LAST + 2, note).font = NOTE
    return row + 1


def blank_line(ws, row: int, label: str, fmt=MONEY, font=INPUT,
               only_est: bool = False, indent: int = 1, note: str = "") -> int:
    """An input row: empty cells the user fills, styled blue."""
    cell = ws.cell(row, 1, label)
    cell.alignment = Alignment(indent=indent)
    start = FIRST_EST if only_est else FIRST
    for c in range(start, LAST + 1):
        cc = ws.cell(row, c)
        cc.font = font
        cc.number_format = fmt
    if note:
        ws.cell(row, LAST + 2, note).font = NOTE
    return row + 1


def check_row(ws, row: int, label: str, formulas: list[str]) -> int:
    cell = ws.cell(row, 1, label)
    cell.font = SECTION
    cell.fill = CHECK_FILL
    for i, f in enumerate(formulas):
        c = ws.cell(row, FIRST + i, f)
        c.font = FORMULA
        c.number_format = MONEY
        c.fill = CHECK_FILL
        c.border = TOP_BORDER
    ws.cell(row, LAST + 2, "must be zero").font = NOTE
    return row + 1


# ---------------------------------------------------------------------------


def build(path: Path) -> None:
    wb = Workbook()

    # === README ============================================================
    ws = wb.active
    ws.title = "README"
    ws.column_dimensions["A"].width = 100
    rows = [
        ("Three-statement model and DCF — blank template", TITLE),
        ("", NOTE),
        ("HOW TO USE IT", SECTION),
        ("1. Fill in the three actual years on IS, BS and CF from the 10-K.", None),
        ("2. Set the drivers on Assumptions. Everything else computes.", None),
        ("3. Watch the two check rows. If either is non-zero, stop and fix it.", None),
        ("", None),
        ("COLOUR CONVENTION — this is how someone else reads your model", SECTION),
        ("BLUE   a hardcoded input. You type it.", INPUT),
        ("BLACK  a formula. Never type over it.", FORMULA),
        ("GREEN  a link to another sheet.", LINK),
        ("", None),
        ("A blue number inside the income statement means something is wrong:", NOTE),
        ("assumptions belong on the Assumptions tab and nowhere else. The rule", NOTE),
        ("sounds pedantic and it is the one thing that keeps a model auditable", NOTE),
        ("after a month away from it.", NOTE),
        ("", None),
        ("THE TWO CHECKS", SECTION),
        ("Balance check   assets - (liabilities + equity). Must be zero.", None),
        ("Cash tie        closing cash on BS vs the cash flow statement. Zero.", None),
        ("", None),
        ("A three-statement model that does not tie is not a model. These are", NOTE),
        ("the first rows a reviewer looks at, before any assumption.", NOTE),
        ("", None),
        ("TAB ORDER, and why it is this order", SECTION),
        ("Assumptions   every input in one place", None),
        ("IS            revenue down to net income", None),
        ("BS            needs IS for retained earnings", None),
        ("CF            derived from IS and the change in BS. Never hardcoded.", None),
        ("DCF           unlevered FCF, WACC, terminal value, sensitivity", None),
        ("Comps         trading multiples against peers", None),
        ("Ratios        margins, returns, leverage, working capital days", None),
        ("", None),
        ("ONE THING THE TEMPLATE CANNOT GIVE YOU", SECTION),
        ("A model is a calculator for a view. It does not contain the view.", NOTE),
        ("The revenue growth and margin assumptions are where the analysis", NOTE),
        ("actually lives, and a tidy model around careless drivers is worse", NOTE),
        ("than a rough model around considered ones, because it looks right.", NOTE),
    ]
    for i, (text, font) in enumerate(rows, start=1):
        c = ws.cell(i, 1, text)
        if font:
            c.font = font

    # === ASSUMPTIONS =======================================================
    ws = wb.create_sheet("Assumptions")
    r = header(ws, "Assumptions", "Every input in the model lives here. Blue only.")
    r = section(ws, r, "REVENUE")
    r = blank_line(ws, r, "Revenue growth %", PCT, only_est=True,
                   note="the single most important input")
    r = section(ws, r, "MARGINS")
    r = blank_line(ws, r, "Gross margin %", PCT, only_est=True)
    r = blank_line(ws, r, "R&D % of revenue", PCT, only_est=True)
    r = blank_line(ws, r, "S&M % of revenue", PCT, only_est=True)
    r = blank_line(ws, r, "G&A % of revenue", PCT, only_est=True)
    r = section(ws, r, "BELOW THE LINE")
    r = blank_line(ws, r, "D&A % of revenue", PCT, only_est=True)
    r = blank_line(ws, r, "Interest rate on debt %", PCT, only_est=True)
    r = blank_line(ws, r, "Effective tax rate %", PCT, only_est=True,
                   note="not the statutory rate")
    r = section(ws, r, "CAPITAL")
    r = blank_line(ws, r, "Capex % of revenue", PCT, only_est=True)
    r = blank_line(ws, r, "Dividends % of net income", PCT, only_est=True)
    r = blank_line(ws, r, "Buyback $", MONEY, only_est=True)
    r = section(ws, r, "WORKING CAPITAL (days)")
    r = blank_line(ws, r, "Receivable days (DSO)", TWO, only_est=True)
    r = blank_line(ws, r, "Inventory days (DIO)", TWO, only_est=True)
    r = blank_line(ws, r, "Payable days (DPO)", TWO, only_est=True)
    r += 1
    r = section(ws, r, "DISCOUNT RATE — feeds the DCF")
    wacc_start = r
    for label, note in [
        ("Risk-free rate", "10Y Treasury"),
        ("Equity risk premium", "Damodaran implied, ~4.5%"),
        ("Beta", "levered"),
        ("Cost of debt (pre-tax)", "yield on existing debt"),
        ("Debt / (debt + equity)", "market values, not book"),
        ("Tax rate for WACC", "marginal"),
    ]:
        ws.cell(r, 1, label).alignment = Alignment(indent=1)
        c = ws.cell(r, FIRST)
        c.font = INPUT
        c.number_format = PCT if "Beta" not in label else TWO
        ws.cell(r, LAST + 2, note).font = NOTE
        r += 1
    rf, erp, beta, kd, dw, tax = (wacc_start + i for i in range(6))
    ws.cell(r, 1, "Cost of equity").alignment = Alignment(indent=1)
    ws.cell(r, FIRST, f"=B{rf}+B{beta}*B{erp}").font = FORMULA
    ws.cell(r, FIRST).number_format = PCT
    ws.cell(r, LAST + 2, "CAPM: rf + beta x ERP").font = NOTE
    ke = r
    r += 1
    ws.cell(r, 1, "WACC").font = SECTION
    ws.cell(r, FIRST, f"=(1-B{dw})*B{ke}+B{dw}*B{kd}*(1-B{tax})").font = FORMULA
    ws.cell(r, FIRST).number_format = PCT
    ws.cell(r, FIRST).fill = CHECK_FILL
    wacc_cell = f"Assumptions!B{r}"
    r += 2
    r = section(ws, r, "TERMINAL VALUE")
    ws.cell(r, 1, "Terminal growth rate").alignment = Alignment(indent=1)
    ws.cell(r, FIRST).font = INPUT
    ws.cell(r, FIRST).number_format = PCT
    ws.cell(r, LAST + 2, "cap at ~3%: nominal GDP. Above 4% the company "
                         "eventually becomes the whole economy.").font = NOTE
    tg_cell = f"Assumptions!B{r}"
    r += 1
    ws.cell(r, 1, "Shares outstanding (diluted)").alignment = Alignment(indent=1)
    ws.cell(r, FIRST).font = INPUT
    ws.cell(r, FIRST).number_format = MONEY
    sh_cell = f"Assumptions!B{r}"
    r += 1
    ws.cell(r, 1, "Current share price").alignment = Alignment(indent=1)
    ws.cell(r, FIRST).font = INPUT
    ws.cell(r, FIRST).number_format = TWO
    px_cell = f"Assumptions!B{r}"

    A = {"growth": 7, "gm": 10, "rd": 11, "sm": 12, "ga": 13, "da": 16,
         "intrate": 17, "tax": 18, "capex": 20, "divpct": 21, "buyback": 22,
         "dso": 24, "dio": 25, "dpo": 26}

    # === INCOME STATEMENT ==================================================
    ws = wb.create_sheet("IS")
    r = header(ws, "Income Statement",
               "Fill the three A columns from the 10-K. E onward computes.")
    r = section(ws, r, "")
    rev = r
    ws.cell(r, 1, "Revenue").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            prev = COLS[i - 1]
            c.value = f"={prev}{r}*(1+Assumptions!{col}{A['growth']})"
            c.font = FORMULA
        c.number_format = MONEY
    r += 1
    cogs = r
    ws.cell(r, 1, "Cost of revenue").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-{col}{rev}*(1-Assumptions!{col}{A['gm']})"
            c.font = FORMULA
        c.number_format = MONEY
    r += 1
    gp = r
    r = line(ws, r, "Gross profit",
             [f"=SUM({c}{rev}:{c}{cogs})" for c in COLS])
    ws.cell(gp, 1).font = SECTION
    r = section(ws, r, "OPERATING EXPENSES")
    opex_start = r
    for key, label in (("rd", "Research and development"),
                       ("sm", "Sales and marketing"),
                       ("ga", "General and administrative")):
        ws.cell(r, 1, label).alignment = Alignment(indent=1)
        for i, col in enumerate(COLS):
            c = ws.cell(r, FIRST + i)
            if i < 3:
                c.font = INPUT
            else:
                c.value = f"=-{col}{rev}*Assumptions!{col}{A[key]}"
                c.font = FORMULA
            c.number_format = MONEY
        r += 1
    opex_end = r - 1
    ebit = r
    r = line(ws, r, "Operating income (EBIT)",
             [f"={c}{gp}+SUM({c}{opex_start}:{c}{opex_end})" for c in COLS])
    ws.cell(ebit, 1).font = SECTION
    r += 1
    interest = r
    ws.cell(r, 1, "Interest expense, net").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-BS!{col}{BS_DEBT_ROW}*Assumptions!{col}{A['intrate']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    pretax = r
    r = line(ws, r, "Pre-tax income",
             [f"={c}{ebit}+{c}{interest}" for c in COLS])
    taxes = r
    ws.cell(r, 1, "Income tax").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-{col}{pretax}*Assumptions!{col}{A['tax']}"
            c.font = FORMULA
        c.number_format = MONEY
    r += 1
    ni = r
    r = line(ws, r, "Net income",
             [f"={c}{pretax}+{c}{taxes}" for c in COLS])
    ws.cell(ni, 1).font = SECTION
    for c in COLS:
        ws.cell(ni, FIRST + COLS.index(c)).border = TOP_BORDER
    r += 1
    r = line(ws, r, "Diluted EPS",
             [f"={c}{ni}/{sh_cell}" for c in COLS], TWO, LINK)
    r += 1
    r = section(ws, r, "MARGIN CHECK")
    r = line(ws, r, "Gross margin %", [f"={c}{gp}/{c}{rev}" for c in COLS], PCT)
    r = line(ws, r, "Operating margin %", [f"={c}{ebit}/{c}{rev}" for c in COLS], PCT)
    r = line(ws, r, "Net margin %", [f"={c}{ni}/{c}{rev}" for c in COLS], PCT)
    IS = {"rev": rev, "gp": gp, "ebit": ebit, "ni": ni, "taxes": taxes,
          "interest": interest, "pretax": pretax}

    # === BALANCE SHEET =====================================================
    ws = wb.create_sheet("BS")
    r = header(ws, "Balance Sheet",
               "Working capital is driven by the days assumptions. Watch the check.")
    r = section(ws, r, "ASSETS")
    cash = r
    ws.cell(r, 1, "Cash and equivalents").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            prev = COLS[i - 1]
            c.value = f"={prev}{r}+CF!{col}{CF_NET_CHANGE_ROW}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    ar = r
    ws.cell(r, 1, "Accounts receivable").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=IS!{col}{IS['rev']}/365*Assumptions!{col}{A['dso']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    inv = r
    ws.cell(r, 1, "Inventory").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = (f"=IS!{col}{IS['rev']}*(1-Assumptions!{col}{A['gm']})"
                       f"/365*Assumptions!{col}{A['dio']}")
            c.font = LINK
        c.number_format = MONEY
    r += 1
    ppe = r
    ws.cell(r, 1, "Net PP&E").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            prev = COLS[i - 1]
            c.value = (f"={prev}{r}+IS!{col}{IS['rev']}*Assumptions!{col}{A['capex']}"
                       f"-IS!{col}{IS['rev']}*Assumptions!{col}{A['da']}")
            c.font = LINK
        c.number_format = MONEY
    r += 1
    gw = r
    r = blank_line(ws, r, "Goodwill and intangibles", MONEY,
                   note="held flat unless you model a deal")
    other_a = r
    r = blank_line(ws, r, "Other assets", MONEY)
    ta = r
    r = line(ws, r, "Total assets",
             [f"=SUM({c}{cash}:{c}{other_a})" for c in COLS])
    ws.cell(ta, 1).font = SECTION
    r += 1
    r = section(ws, r, "LIABILITIES")
    ap = r
    ws.cell(r, 1, "Accounts payable").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=IS!{col}{IS['rev']}*(1-Assumptions!{col}{A['gm']})/365*Assumptions!{col}{A['dpo']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    accrued = r
    r = blank_line(ws, r, "Accrued liabilities", MONEY)
    debt = r
    r = blank_line(ws, r, "Total debt", MONEY,
                   note=f"row {BS_DEBT_ROW}. IS interest expense and CF change "
                        f"in debt both reference it.")
    other_l = r
    r = blank_line(ws, r, "Other liabilities", MONEY)
    tl = r
    r = line(ws, r, "Total liabilities",
             [f"=SUM({c}{ap}:{c}{other_l})" for c in COLS])
    ws.cell(tl, 1).font = SECTION
    r += 1
    r = section(ws, r, "EQUITY")
    paid = r
    r = blank_line(ws, r, "Paid-in capital", MONEY)
    re_row = r
    ws.cell(r, 1, "Retained earnings").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            prev = COLS[i - 1]
            c.value = (f"={prev}{r}+IS!{col}{IS['ni']}"
                       f"-IS!{col}{IS['ni']}*Assumptions!{col}{A['divpct']}")
            c.font = LINK
        c.number_format = MONEY
    r += 1
    te = r
    r = line(ws, r, "Total equity", [f"=SUM({c}{paid}:{c}{re_row})" for c in COLS])
    ws.cell(te, 1).font = SECTION
    r += 1
    r = check_row(ws, r, "BALANCE CHECK",
                  [f"={c}{ta}-({c}{tl}+{c}{te})" for c in COLS])
    BS = {"cash": cash, "ar": ar, "inv": inv, "ppe": ppe, "ap": ap,
          "debt": debt, "ta": ta, "tl": tl, "te": te}

    # === CASH FLOW =========================================================
    ws = wb.create_sheet("CF")
    r = header(ws, "Cash Flow Statement",
               "Entirely derived. Nothing on this sheet should ever be blue.")
    r = section(ws, r, "OPERATING")
    cf_ni = r
    r = line(ws, r, "Net income", [f"=IS!{c}{IS['ni']}" for c in COLS], MONEY, LINK)
    cf_da = r
    ws.cell(r, 1, "Depreciation and amortisation").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=IS!{col}{IS['rev']}*Assumptions!{col}{A['da']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    r = section(ws, r, "CHANGE IN WORKING CAPITAL")
    wc_start = r
    for label, bs_row in (("(Increase) in receivables", BS["ar"]),
                          ("(Increase) in inventory", BS["inv"]),
                          ("Increase in payables", BS["ap"])):
        ws.cell(r, 1, label).alignment = Alignment(indent=1)
        sign = "-" if "Increase) in" in label else ""
        for i, col in enumerate(COLS):
            c = ws.cell(r, FIRST + i)
            if i < 3:
                c.font = INPUT
            else:
                prev = COLS[i - 1]
                c.value = f"={sign}(BS!{col}{bs_row}-BS!{prev}{bs_row})"
                c.font = LINK
            c.number_format = MONEY
        r += 1
    wc_end = r - 1
    cfo = r
    r = line(ws, r, "Cash flow from operations",
             [f"={c}{cf_ni}+{c}{cf_da}+SUM({c}{wc_start}:{c}{wc_end})" for c in COLS])
    ws.cell(cfo, 1).font = SECTION
    r += 1
    r = section(ws, r, "INVESTING")
    capex_row = r
    ws.cell(r, 1, "Capital expenditure").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-IS!{col}{IS['rev']}*Assumptions!{col}{A['capex']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    acq = r
    r = blank_line(ws, r, "Acquisitions and other", MONEY)
    cfi = r
    r = line(ws, r, "Cash flow from investing",
             [f"=SUM({c}{capex_row}:{c}{acq})" for c in COLS])
    ws.cell(cfi, 1).font = SECTION
    r += 1
    r = section(ws, r, "FINANCING")
    div = r
    ws.cell(r, 1, "Dividends paid").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-IS!{col}{IS['ni']}*Assumptions!{col}{A['divpct']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    bb = r
    ws.cell(r, 1, "Share repurchases").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            c.value = f"=-Assumptions!{col}{A['buyback']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    dchg = r
    ws.cell(r, 1, "Change in debt").alignment = Alignment(indent=1)
    for i, col in enumerate(COLS):
        c = ws.cell(r, FIRST + i)
        if i < 3:
            c.font = INPUT
        else:
            prev = COLS[i - 1]
            c.value = f"=BS!{col}{BS['debt']}-BS!{prev}{BS['debt']}"
            c.font = LINK
        c.number_format = MONEY
    r += 1
    cff = r
    r = line(ws, r, "Cash flow from financing",
             [f"=SUM({c}{div}:{c}{dchg})" for c in COLS])
    ws.cell(cff, 1).font = SECTION
    r += 1
    net = r
    r = line(ws, r, "Net change in cash",
             [f"={c}{cfo}+{c}{cfi}+{c}{cff}" for c in COLS])
    ws.cell(net, 1).font = SECTION
    for i in range(len(COLS)):
        ws.cell(net, FIRST + i).border = TOP_BORDER
    r += 1
    r = check_row(ws, r, "CASH TIE  (BS cash movement less CF)",
                  ["=0"] + [f"=(BS!{c}{BS['cash']}-BS!{COLS[i]}{BS['cash']})-{c}{net}"
                            for i, c in enumerate(COLS[1:])])
    r += 1
    r = line(ws, r, "Free cash flow (CFO less capex)",
             [f"={c}{cfo}+{c}{capex_row}" for c in COLS])
    ws.cell(r - 1, 1).font = SECTION
    CF = {"cfo": cfo, "capex": capex_row, "da": cf_da, "net": net,
          "wc_start": wc_start, "wc_end": wc_end}

    # === DCF ===============================================================
    ws = wb.create_sheet("DCF")
    r = header(ws, "Discounted Cash Flow", "Unlevered FCF. Read the sensitivity, "
                                           "not the point estimate.")
    r = section(ws, r, "UNLEVERED FREE CASH FLOW")
    e_ebit = r
    r = line(ws, r, "EBIT", [""] * 3 + [f"=IS!{c}{IS['ebit']}" for c in EST],
             MONEY, LINK)
    e_tax = r
    r = line(ws, r, "Less: taxes on EBIT",
             [""] * 3 + [f"=-IS!{c}{IS['ebit']}*Assumptions!{c}{A['tax']}" for c in EST],
             MONEY, LINK)
    nopat = r
    r = line(ws, r, "NOPAT", [""] * 3 + [f"={c}{e_ebit}+{c}{e_tax}" for c in EST])
    ws.cell(nopat, 1).font = SECTION
    e_da = r
    r = line(ws, r, "Plus: D&A", [""] * 3 + [f"=CF!{c}{CF['da']}" for c in EST],
             MONEY, LINK)
    e_capex = r
    r = line(ws, r, "Less: capex", [""] * 3 + [f"=CF!{c}{CF['capex']}" for c in EST],
             MONEY, LINK)
    e_wc = r
    r = line(ws, r, "Less: change in working capital",
             [""] * 3 + [f"=SUM(CF!{c}{CF['wc_start']}:CF!{c}{CF['wc_end']})" for c in EST],
             MONEY, LINK)
    ufcf = r
    # NOPAT + D&A - capex - change in working capital. capex and the WC change
    # are already negative on the CF sheet, so this is a plain sum rather than
    # a string of subtractions -- which is also why the sign convention on CF
    # has to stay consistent.
    r = line(ws, r, "Unlevered free cash flow",
             [""] * 3 + [f"=SUM({c}{nopat}:{c}{e_wc})" for c in EST])
    ws.cell(ufcf, 1).font = SECTION
    for c in EST:
        ws.cell(ufcf, FIRST + COLS.index(c)).border = TOP_BORDER
    r += 1
    per = r
    r = line(ws, r, "Discount period", [""] * 3 + [str(i + 1) for i in range(len(EST))],
             TWO, FORMULA, note="mid-year convention would use i-0.5")
    disc = r
    r = line(ws, r, "Discount factor",
             [""] * 3 + [f"=1/(1+{wacc_cell})^{c}{per}" for c in EST], TWO)
    pv = r
    r = line(ws, r, "PV of FCF", [""] * 3 + [f"={c}{ufcf}*{c}{disc}" for c in EST])
    r += 1
    r = section(ws, r, "VALUATION")
    last_e = EST[-1]
    sum_pv = r
    r = line(ws, r, "Sum of PV, explicit period",
             [f"=SUM({EST[0]}{pv}:{last_e}{pv})"])
    tv = r
    r = line(ws, r, "Terminal value (perpetuity)",
             [f"={last_e}{ufcf}*(1+{tg_cell})/({wacc_cell}-{tg_cell})"],
             MONEY, FORMULA, note="Gordon growth. Diverges if g >= WACC.")
    pv_tv = r
    r = line(ws, r, "PV of terminal value", [f"=B{tv}*{last_e}{disc}"])
    ev = r
    r = line(ws, r, "Enterprise value", [f"=B{sum_pv}+B{pv_tv}"])
    ws.cell(ev, 1).font = SECTION
    r = line(ws, r, "Terminal value as % of EV", [f"=B{pv_tv}/B{ev}"], PCT,
             FORMULA, note="above 75% and the answer is your perpetuity "
                           "assumption, not the business")
    tv_pct = r - 1
    ws.cell(tv_pct, FIRST).fill = CHECK_FILL
    r += 1
    nd = r
    r = line(ws, r, "Less: net debt",
             [f"=BS!{COLS[2]}{BS['debt']}-BS!{COLS[2]}{BS['cash']}"], MONEY, LINK,
             note="last actual year")
    eqv = r
    r = line(ws, r, "Equity value", [f"=B{ev}-B{nd}"])
    ws.cell(eqv, 1).font = SECTION
    vps = r
    r = line(ws, r, "Value per share", [f"=B{eqv}/{sh_cell}"], TWO)
    ws.cell(vps, 1).font = SECTION
    ws.cell(vps, FIRST).fill = CHECK_FILL
    r = line(ws, r, "Upside / (downside) to price",
             [f"=B{vps}/{px_cell}-1"], PCT)
    r += 2
    r = section(ws, r, "SENSITIVITY — value per share")
    ws.cell(r, 1, "WACC down the side, terminal growth across the top.").font = NOTE
    r += 1
    grid_top = r
    ws.cell(r, FIRST - 1 + 1, "").font = NOTE
    for j in range(5):
        offset = (j - 2) * 0.005
        c = ws.cell(r, FIRST + 1 + j, f"={tg_cell}{offset:+g}")
        c.font = FORMULA
        c.number_format = PCT
        c.fill = SECTION_FILL
    r += 1
    for i in range(5):
        offset = (i - 2) * 0.005
        wc = ws.cell(r, FIRST, f"={wacc_cell}{offset:+g}")
        wc.font = FORMULA
        wc.number_format = PCT
        wc.fill = SECTION_FILL
        for j in range(5):
            gcol = get_column_letter(FIRST + 1 + j)
            tvf = (f"({last_e}{ufcf}*(1+{gcol}${grid_top})"
                   f"/($B{r}-{gcol}${grid_top}))*{last_e}{disc}")
            cell = ws.cell(r, FIRST + 1 + j,
                           f"=IF({gcol}${grid_top}>=$B{r},NA(),"
                           f"(B{sum_pv}+{tvf}-B{nd})/{sh_cell})")
            cell.font = FORMULA
            cell.number_format = TWO
        r += 1
    r += 1
    ws.cell(r, 1, "The grid is the output, not the single number above it. If two "
                  "inputs moving 100bp").font = NOTE
    ws.cell(r + 1, 1, "swing the answer by 50%, that spread is the honest width "
                      "of the valuation.").font = NOTE

    # === COMPS =============================================================
    ws = wb.create_sheet("Comps")
    ws["A1"] = "Trading Comparables"
    ws["A1"].font = TITLE
    ws["A2"] = "Multiples are only informative against a peer set and the "\
               "company's own history."
    ws["A2"].font = NOTE
    heads = ["Company", "Ticker", "Price", "Diluted shares", "Market cap",
             "Net debt", "EV", "Revenue", "EBITDA", "EBIT", "Net income",
             "EV/Revenue", "EV/EBITDA", "EV/EBIT", "P/E", "Rev growth %",
             "EBITDA margin %"]
    for j, h in enumerate(heads, start=1):
        c = ws.cell(4, j, h)
        c.font = HEAD
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = 15 if j > 2 else 22
    for row in range(5, 13):
        for j in range(1, 12):
            cc = ws.cell(row, j)
            cc.font = INPUT
            cc.number_format = MONEY if j > 2 else "General"
        ws.cell(row, 5, f"=C{row}*D{row}").font = FORMULA
        ws.cell(row, 7, f"=E{row}+F{row}").font = FORMULA
        for j, f in ((12, f"=IF(H{row}=0,NA(),G{row}/H{row})"),
                     (13, f"=IF(I{row}=0,NA(),G{row}/I{row})"),
                     (14, f"=IF(J{row}=0,NA(),G{row}/J{row})"),
                     (15, f"=IF(K{row}<=0,NA(),E{row}/K{row})")):
            cc = ws.cell(row, j, f)
            cc.font = FORMULA
            cc.number_format = MULT
        for j in (16, 17):
            cc = ws.cell(row, j)
            cc.font = INPUT
            cc.number_format = PCT
        ws.cell(row, 17, f"=IF(H{row}=0,NA(),I{row}/H{row})").font = FORMULA
    for label, fn, row in (("Mean", "AVERAGE", 14), ("Median", "MEDIAN", 15),
                           ("High", "MAX", 16), ("Low", "MIN", 17)):
        ws.cell(row, 1, label).font = SECTION
        for j in range(12, 18):
            col = get_column_letter(j)
            c = ws.cell(row, j, f"={fn}({col}5:{col}12)")
            c.font = FORMULA
            c.number_format = MULT if j < 16 else PCT
    ws.cell(19, 1, "Median is the one to quote. A single outlier moves the mean "
                   "and tells you nothing.").font = NOTE

    # === RATIOS ============================================================
    ws = wb.create_sheet("Ratios")
    r = header(ws, "Ratio Analysis", "All computed. The trend matters more than "
                                     "any single year.")
    r = section(ws, r, "GROWTH")
    r = line(ws, r, "Revenue growth %",
             [""] + [f"=IS!{c}{IS['rev']}/IS!{COLS[i]}{IS['rev']}-1"
                     for i, c in enumerate(COLS[1:])], PCT, LINK)
    r = line(ws, r, "EBIT growth %",
             [""] + [f"=IFERROR(IS!{c}{IS['ebit']}/IS!{COLS[i]}{IS['ebit']}-1,NA())"
                     for i, c in enumerate(COLS[1:])], PCT, LINK)
    r = section(ws, r, "PROFITABILITY")
    r = line(ws, r, "Gross margin %",
             [f"=IS!{c}{IS['gp']}/IS!{c}{IS['rev']}" for c in COLS], PCT, LINK)
    r = line(ws, r, "EBIT margin %",
             [f"=IS!{c}{IS['ebit']}/IS!{c}{IS['rev']}" for c in COLS], PCT, LINK)
    r = line(ws, r, "Net margin %",
             [f"=IS!{c}{IS['ni']}/IS!{c}{IS['rev']}" for c in COLS], PCT, LINK)
    r = line(ws, r, "FCF margin %",
             [f"=(CF!{c}{CF['cfo']}+CF!{c}{CF['capex']})/IS!{c}{IS['rev']}"
              for c in COLS], PCT, LINK)
    r = section(ws, r, "RETURNS — the test that matters")
    ic = r
    r = line(ws, r, "Invested capital",
             [f"=BS!{c}{BS['debt']}+BS!{c}{BS['te']}-BS!{c}{BS['cash']}"
              for c in COLS], MONEY, LINK)
    r = line(ws, r, "NOPAT",
             [f"=IS!{c}{IS['ebit']}*(1-Assumptions!{c}{A['tax']})" for c in COLS],
             MONEY, LINK)
    nopat_r = r - 1
    roic = r
    r = line(ws, r, "ROIC %",
             [f"=IFERROR({c}{nopat_r}/{c}{ic},NA())" for c in COLS], PCT)
    ws.cell(roic, 1).font = SECTION
    r = line(ws, r, "WACC %", [f"={wacc_cell}" for c in COLS], PCT, LINK)
    wacc_r = r - 1
    spread = r
    r = line(ws, r, "ROIC less WACC (the value spread)",
             [f"=IFERROR({c}{roic}-{c}{wacc_r},NA())" for c in COLS], PCT)
    ws.cell(spread, 1).font = SECTION
    for i in range(len(COLS)):
        ws.cell(spread, FIRST + i).fill = CHECK_FILL
    ws.cell(spread, LAST + 2, "negative means growth DESTROYS value").font = NOTE
    r += 1
    r = section(ws, r, "LEVERAGE")
    r = line(ws, r, "Net debt",
             [f"=BS!{c}{BS['debt']}-BS!{c}{BS['cash']}" for c in COLS], MONEY, LINK)
    nd_r = r - 1
    r = line(ws, r, "Net debt / EBITDA",
             [f"=IFERROR({c}{nd_r}/(IS!{c}{IS['ebit']}+CF!{c}{CF['da']}),NA())"
              for c in COLS], MULT)
    r = line(ws, r, "EBIT / interest (coverage)",
             [f"=IFERROR(IS!{c}{IS['ebit']}/-IS!{c}{IS['interest']},NA())"
              for c in COLS], MULT)
    r = section(ws, r, "WORKING CAPITAL (days)")
    r = line(ws, r, "DSO",
             [f"=BS!{c}{BS['ar']}/IS!{c}{IS['rev']}*365" for c in COLS], TWO, LINK)
    r = line(ws, r, "DPO",
             [f"=IFERROR(BS!{c}{BS['ap']}/(IS!{c}{IS['rev']}-IS!{c}{IS['gp']})*365,NA())"
              for c in COLS], TWO, LINK)
    r += 1
    ws.cell(r, 1, "Read ROIC less WACC first. A business earning less on capital "
                  "than capital costs").font = NOTE
    ws.cell(r + 1, 1, "destroys value every time it reinvests, and growth makes "
                      "that worse, not better.").font = NOTE

    wb.save(path)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "Financial_Analysis_Template.xlsx"
    build(out)
    print(f"wrote {out}")
