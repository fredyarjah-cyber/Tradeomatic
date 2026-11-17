# Minimum commission in the paper model

`ExecutionAssumptions.minimum_commission_per_fill` is a nonnegative USD amount. Old stored assumptions default to zero for compatibility; this default does not establish the account commission schedule or mark any costs validated.

A modeled fill charges the larger of units times `commission_per_unit` and the minimum. No fee is charged for zero units. Each partial exit incurs its own fee. Entry commission is allocated proportionally across exits so it is counted exactly once in total realized P&L.

Sizing reserves commission for one entry and up to two exits. Its conservative bound is entry fee plus proportional exit commission plus two minimum charges. This can exceed actual fees. Risk, net targets, cost-to-stop checks, approval quotes and entry reward/risk use that reserve. A budget too small for minimum fees rejects the position. Gap risk and more than two exit fills are outside this deterministic paper model.

This implements a model capability only. OANDA observations remain evidence, with no automatic context writes or cost validation. Slippage, financing, event coverage and the account commission schedule still require independent validation. Execution permissions are unchanged.

Reference: https://developer.oanda.com/rest-live-v20/primitives-df/ (InstrumentCommission: account-home-currency commission, unitsTraded and minimumCommission per fill). The OANDA observation pilot accepts USD accounts only.
