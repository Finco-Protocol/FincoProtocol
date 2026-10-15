# WF-A credit validation matrix

A successful stress Run is not a validation PASS, and a credit identity PASS does not establish bankability. Directional expectations follow the product's actual sizing mechanics.

Metric rows: {'PASS': 144, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_COMPARABLE': 0}  ·  Directional checks: {'PASS': 56, 'FAIL': 0, 'UNAVAILABLE': 0, 'NOT_ASSERTED': 3}

## Reported vs independently recomputed

| Case | Run | Assumption delta | Metric | Reported | Independent | Signed difference | Allowance | Result |
|---|---|---|---|---|---|---|---|---|
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Senior debt quantum (solver final size vs Sources & Uses) | 6769.603805 | 6769.603805 | 0.000000000000 | 0.000001 | PASS |
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Average DSCR (reported vs recomputed) | 1.232709 | 1.232709 | -0.000000 | 0.000000 | PASS |
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Total Senior debt service (reported vs scheduled sum) | 8955.895544 | 8955.895544 | 0.000000 | 0.000001 | PASS |
| solar-R0 | `448920d6` | baseline, DSCR-sized, P50 lender case | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Senior debt quantum (solver final size vs Sources & Uses) | 6724.968784 | 6724.968784 | 0.000000000000 | 0.000001 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Average DSCR (reported vs recomputed) | 1.217780 | 1.217780 | 0.000000 | 0.000000 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Total Senior debt service (reported vs scheduled sum) | 10139.857186 | 10139.857186 | -0.000000 | 0.000001 | PASS |
| solar-R-hours-30 | `5916f6cb` | P50 generation hours -30% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Senior debt quantum (solver final size vs Sources & Uses) | 6686.144921 | 6686.144921 | 0.000000000000 | 0.000001 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Minimum DSCR (reported vs recomputed) | 1.042971 | 1.042971 | 0.000000 | 0.000000 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Average DSCR (reported vs recomputed) | 1.850467 | 1.850467 | 0.000000 | 0.000000 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Total Senior debt service (reported vs scheduled sum) | 9515.820506 | 9515.820506 | -0.000000 | 0.000001 | PASS |
| solar-F0 | `121aa3df` | baseline, GEARING_CAP (debt sized on cost) | Periods in lock-up (reported vs closed-gate periods) | 1 | 1 | 0 | 0.000000 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Senior debt quantum (solver final size vs Sources & Uses) | 6686.144921 | 6686.144921 | 0.000000000000 | 0.000001 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Minimum DSCR (reported vs recomputed) | 0.702586 | 0.702586 | -0.000000 | 0.000000 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Average DSCR (reported vs recomputed) | 1.352503 | 1.352503 | -0.000000 | 0.000000 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Total Senior debt service (reported vs scheduled sum) | 9515.820506 | 9515.820506 | -0.000000 | 0.000001 | PASS |
| solar-F-hours-30 | `548a0914` | P50 generation hours -30% | Periods in lock-up (reported vs closed-gate periods) | 12 | 12 | 0 | 0.000000 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Senior debt quantum (solver final size vs Sources & Uses) | 6731.465445 | 6731.465445 | 0.00000000000 | 0.000001 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Minimum DSCR (reported vs recomputed) | 1.275620 | 1.275620 | 0.000000 | 0.000000 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Average DSCR (reported vs recomputed) | 1.341663 | 1.341663 | -0.000000 | 0.000000 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Total Senior debt service (reported vs scheduled sum) | 9181.159814 | 9181.159814 | -0.000000 | 0.000001 | PASS |
| solar-L-P90 | `67de0647` | P90-10y lender case vs P50 | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Senior debt quantum (solver final size vs Sources & Uses) | 6883.275066 | 6883.275066 | 0.000000000000 | 0.000001 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Average DSCR (reported vs recomputed) | 1.246089 | 1.246089 | -0.000000 | 0.000000 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Total Senior debt service (reported vs scheduled sum) | 10349.515249 | 10349.515249 | -0.000000 | 0.000001 | PASS |
| solar-R-tariff-30 | `49d89878` | contracted price -30% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Senior debt quantum (solver final size vs Sources & Uses) | 7412.546166 | 7412.546166 | 0.000000000000 | 0.000001 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Average DSCR (reported vs recomputed) | 1.268737 | 1.268737 | -0.000000 | 0.000000 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Total Senior debt service (reported vs scheduled sum) | 10062.381256 | 10062.381256 | 0.000000 | 0.000001 | PASS |
| solar-R-capex+10 | `d663298c` | CAPEX contingency +10% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Senior debt quantum (solver final size vs Sources & Uses) | 6756.448198 | 6756.448198 | 0.0000000000000 | 0.000001 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Average DSCR (reported vs recomputed) | 1.250275 | 1.250275 | -0.000000 | 0.000000 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Total Senior debt service (reported vs scheduled sum) | 9044.602314 | 9044.602314 | 0.000000 | 0.000001 | PASS |
| solar-R-opex+50 | `b99ab0da` | OPEX contingency +50% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Senior debt quantum (solver final size vs Sources & Uses) | 6769.603805 | 6769.603805 | 0.000000000000 | 0.000001 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Average DSCR (reported vs recomputed) | 1.232709 | 1.232709 | -0.000000 | 0.000000 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Total Senior debt service (reported vs scheduled sum) | 8955.895544 | 8955.895544 | 0.000000 | 0.000001 | PASS |
| solar-R-rate-5.5 | `2d2ec7fc` | explicit all-in rate 5.50% (control for the explicit schedule route) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 6793.338469 | 6793.338469 | 0.000000000000 | 0.000001 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Average DSCR (reported vs recomputed) | 1.225259 | 1.225259 | -0.000000 | 0.000000 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 9571.584055 | 9571.584055 | 0.000000 | 0.000001 | PASS |
| solar-R-rate-6.5 | `8a9265db` | all-in rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 6140.532576 | 6140.532576 | 0.000000000000 | 0.000001 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.651524 | 0.651524 | -0.000000 | 0.000000 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Average DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 10337.542353 | 10337.542353 | 0.000000 | 0.000001 | PASS |
| solar-R-combined | `0010a192` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Senior debt quantum (solver final size vs Sources & Uses) | 6583.298481 | 6583.298481 | 0.000000000000 | 0.000001 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Gearing (recorded vs Senior / total uses) | 0.730136 | 0.730136 | -0.000000 | 0.000000 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Average DSCR (reported vs recomputed) | 1.200000 | 1.200000 | -0.000000 | 0.000000 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Total Senior debt service (reported vs scheduled sum) | 8625.642015 | 8625.642015 | 0.000000 | 0.000001 | PASS |
| solar-R-tenor-10 | `356e6662` | short Senior tenor (10 years) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Senior debt quantum (solver final size vs Sources & Uses) | 6769.603805 | 6769.603805 | 0.000000000000 | 0.000001 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Minimum DSCR (reported vs recomputed) | 1.200000 | 1.200000 | 0.000000 | 0.000000 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Average DSCR (reported vs recomputed) | 1.232709 | 1.232709 | -0.000000 | 0.000000 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Total Senior debt service (reported vs scheduled sum) | 8955.895544 | 8955.895544 | 0.000000 | 0.000001 | PASS |
| solar-R-tenor-18 | `0b9aebd5` | long Senior tenor (18 years) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Senior debt quantum (solver final size vs Sources & Uses) | 6686.144921 | 6686.144921 | 0.000000000000 | 0.000001 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Minimum DSCR (reported vs recomputed) | 0.702586 | 0.702586 | -0.000000 | 0.000000 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Average DSCR (reported vs recomputed) | 1.579855 | 1.579855 | -0.000000 | 0.000000 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Total Senior debt service (reported vs scheduled sum) | 9515.820506 | 9515.820506 | -0.000000 | 0.000001 | PASS |
| solar-F-tariff-30 | `edc77ce6` | contracted price -30% | Periods in lock-up (reported vs closed-gate periods) | 12 | 12 | 0 | 0.000000 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Senior debt quantum (solver final size vs Sources & Uses) | 7354.759413 | 7354.759413 | 0.000000000000 | 0.000001 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Minimum DSCR (reported vs recomputed) | 0.948156 | 0.948156 | 0.000000 | 0.000000 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Average DSCR (reported vs recomputed) | 1.705782 | 1.705782 | -0.000000 | 0.000000 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Total Senior debt service (reported vs scheduled sum) | 10467.402556 | 10467.402556 | -0.000000 | 0.000001 | PASS |
| solar-F-capex+10 | `342746b0` | CAPEX contingency +10% | Periods in lock-up (reported vs closed-gate periods) | 1 | 1 | 0 | 0.000000 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Senior debt quantum (solver final size vs Sources & Uses) | 6686.144921 | 6686.144921 | 0.000000000000 | 0.000001 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Minimum DSCR (reported vs recomputed) | 0.997147 | 0.997147 | -0.000000 | 0.000000 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Average DSCR (reported vs recomputed) | 1.784135 | 1.784135 | -0.000000 | 0.000000 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Total Senior debt service (reported vs scheduled sum) | 9515.820506 | 9515.820506 | -0.000000 | 0.000001 | PASS |
| solar-F-opex+50 | `ba7df30c` | OPEX contingency +50% | Periods in lock-up (reported vs closed-gate periods) | 1 | 1 | 0 | 0.000000 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Senior debt quantum (solver final size vs Sources & Uses) | 6686.144921 | 6686.144921 | 0.000000000000 | 0.000001 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Minimum DSCR (reported vs recomputed) | 1.042971 | 1.042971 | 0.000000 | 0.000000 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Average DSCR (reported vs recomputed) | 1.850467 | 1.850467 | 0.000000 | 0.000000 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Total Senior debt service (reported vs scheduled sum) | 9515.820506 | 9515.820506 | -0.000000 | 0.000001 | PASS |
| solar-F-rate-5.5 | `0b3690e0` | explicit all-in rate 5.50% (control) | Periods in lock-up (reported vs closed-gate periods) | 1 | 1 | 0 | 0.000000 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 6732.320091 | 6732.320091 | 0.0000000000000 | 0.000001 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.000000 | 0.000000 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Minimum DSCR (reported vs recomputed) | 0.972725 | 0.972725 | -0.000000 | 0.000000 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Average DSCR (reported vs recomputed) | 1.773418 | 1.773418 | 0.000000 | 0.000000 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 10099.577255 | 10099.577255 | -0.000000 | 0.000001 | PASS |
| solar-F-rate-6.5 | `a99f5fa1` | all-in rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 1 | 1 | 0 | 0.000000 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 7068.936095 | 7068.936095 | 0.0000000000000 | 0.000001 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.00 | 0.000000 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Minimum DSCR (reported vs recomputed) | 0.547312 | 0.547312 | -0.000000 | 0.000000 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Average DSCR (reported vs recomputed) | 1.234756 | 1.234756 | 0.000000 | 0.000000 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 10604.556117 | 10604.556117 | -0.000000 | 0.000001 | PASS |
| solar-F-combined | `382ed069` | combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 24 | 24 | 0 | 0.000000 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Senior debt quantum (solver final size vs Sources & Uses) | 6820.955347 | 6820.955347 | 0.000000000000 | 0.000001 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.00 | 0.000000 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Minimum DSCR (reported vs recomputed) | 1.181297 | 1.181297 | -0.000000 | 0.000000 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Average DSCR (reported vs recomputed) | 2.115070 | 2.115070 | 0.000000 | 0.000000 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Total Senior debt service (reported vs scheduled sum) | 9681.017476 | 9681.017476 | 0.000000 | 0.000001 | PASS |
| solar-L-P90-price-10 | `7c0d3cec` | P90 lender case with price -10% | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 6832.896159 | 6832.896159 | 0.000000000000 | 0.000001 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | -0.000000 | 0.000000 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Minimum DSCR (reported vs recomputed) | 1.238613 | 1.238613 | 0.000000 | 0.000000 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Average DSCR (reported vs recomputed) | 1.454195 | 1.454195 | 0.000000 | 0.000000 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 10058.065084 | 10058.065084 | -0.000000 | 0.000001 | PASS |
| solar-L-P90-rate-6.5 | `4f18eb49` | P90 lender case with rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Senior debt quantum (solver final size vs Sources & Uses) | 7167.710826 | 7167.710826 | 0.000000000000 | 0.000001 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Gearing (recorded vs Senior / total uses) | 0.750000 | 0.750000 | 0.00 | 0.000000 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Minimum DSCR (reported vs recomputed) | 1.156473 | 1.156473 | 0.000000 | 0.000000 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Average DSCR (reported vs recomputed) | 1.323087 | 1.323087 | -0.000000 | 0.000000 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Total Senior debt service (reported vs scheduled sum) | 11319.935620 | 11319.935620 | 0.000000 | 0.000001 | PASS |
| solar-L-downside | `7e7359d2` | combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Senior debt quantum (solver final size vs Sources & Uses) | 5983.854405 | 5983.854405 | 0.000000000000 | 0.000001 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Gearing (recorded vs Senior / total uses) | 0.670000 | 0.670000 | -0.000000 | 0.000000 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Minimum DSCR (reported vs recomputed) | 1.275160 | 1.275160 | 0.000000 | 0.000000 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Average DSCR (reported vs recomputed) | 1.332446 | 1.332446 | 0.000000 | 0.000000 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Total Senior debt service (reported vs scheduled sum) | 7824.591982 | 7824.591982 | 0.000000 | 0.000001 | PASS |
| solar-B-below | `70521879` | tenor 10, gearing cap 67.0% (just BELOW DSCR capacity) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Senior debt quantum (solver final size vs Sources & Uses) | 6021.346013 | 6021.346013 | 0.000000000000 | 0.000001 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Gearing (recorded vs Senior / total uses) | 0.674052 | 0.674052 | -0.000000 | 0.000000 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Minimum DSCR (reported vs recomputed) | 1.275184 | 1.275184 | -0.000000 | 0.000000 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Average DSCR (reported vs recomputed) | 1.317096 | 1.317096 | 0.000000 | 0.000000 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Total Senior debt service (reported vs scheduled sum) | 7889.251674 | 7889.251674 | 0.000000 | 0.000001 | PASS |
| solar-B-above | `9d172dd5` | tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity) | Periods in lock-up (reported vs closed-gate periods) | 0 | 0 | 0 | 0.000000 | PASS |

## Directional checks

| Check | Expectation | From → To | Values | Result |
|---|---|---|---|---|
| solar: fixed debt unchanged under hours-30 | debt quantum unchanged | F0 → F-hours-30 | 6686.144921 → 6686.144921 | PASS |
| solar: fixed debt service unchanged under hours-30 | total Senior service unchanged | F0 → F-hours-30 | 9515.820506 → 9515.820506 | PASS |
| solar: fixed minimum DSCR under hours-30 | minimum DSCR falls | F0 → F-hours-30 | 1.042971 → 0.702586 | PASS |
| solar: fixed lock-up periods under hours-30 | lock-up periods do not fall | F0 → F-hours-30 | 1 → 12 | PASS |
| solar: fixed EBITDA under hours-30 | EBITDA falls | F0 → F-hours-30 | 36953.633862 → 24959.287010 | PASS |
| solar: fixed debt unchanged under tariff-30 | debt quantum unchanged | F0 → F-tariff-30 | 6686.144921 → 6686.144921 | PASS |
| solar: fixed debt service unchanged under tariff-30 | total Senior service unchanged | F0 → F-tariff-30 | 9515.820506 → 9515.820506 | PASS |
| solar: fixed minimum DSCR under tariff-30 | minimum DSCR falls | F0 → F-tariff-30 | 1.042971 → 0.702586 | PASS |
| solar: fixed lock-up periods under tariff-30 | lock-up periods do not fall | F0 → F-tariff-30 | 1 → 12 | PASS |
| solar: fixed EBITDA under tariff-30 | EBITDA falls | F0 → F-tariff-30 | 36953.633862 → 33013.594620 | PASS |
| solar: fixed debt unchanged under opex+50 | debt quantum unchanged | F0 → F-opex+50 | 6686.144921 → 6686.144921 | PASS |
| solar: fixed debt service unchanged under opex+50 | total Senior service unchanged | F0 → F-opex+50 | 9515.820506 → 9515.820506 | PASS |
| solar: fixed minimum DSCR under opex+50 | minimum DSCR falls | F0 → F-opex+50 | 1.042971 → 0.997147 | PASS |
| solar: fixed lock-up periods under opex+50 | lock-up periods do not fall | F0 → F-opex+50 | 1 → 1 | PASS |
| solar: fixed EBITDA under opex+50 | EBITDA falls | F0 → F-opex+50 | 36953.633862 → 35439.872707 | PASS |
| solar: fixed capex+10 raises debt | debt quantum rises (gearing x uses) | F0 → F-capex+10 | 6686.144921 → 7354.759413 | PASS |
| solar: fixed capex+10 raises equity funding | equity funding rises | F0 → F-capex+10 | 2228.714974 → 2451.586471 | PASS |
| solar: fixed capex+10 lowers coverage | minimum DSCR falls | F0 → F-capex+10 | 1.042971 → 0.948156 | PASS |
| solar: fixed rate control | explicit 5.50% schedule equals the default 5.50% case | F0 → F-rate-5.5 | 6686.144921 → 6686.144921 | PASS |
| solar: fixed rate+100bp raises interest | total interest rises | F-rate-5.5 → F-rate-6.5 | 2829.675585 → 3367.257164 | PASS |
| solar: fixed rate+100bp raises service | total Senior service rises | F-rate-5.5 → F-rate-6.5 | 9515.820506 → 10099.577255 | PASS |
| solar: fixed rate+100bp lowers coverage | minimum DSCR falls | F-rate-5.5 → F-rate-6.5 | 1.042971 → 0.972725 | PASS |
| solar: fixed combined downside lowers coverage | minimum DSCR falls | F0 → F-combined | 1.042971 → 0.547312 | PASS |
| solar: resized debt shrinks under hours-30 | re-sized debt quantum falls | R0 → R-hours-30 | 6769.603805 → 6724.968784 | PASS |
| solar: resized EBITDA under hours-30 | EBITDA falls | R0 → R-hours-30 | 36953.633862 → 24959.287010 | PASS |
| solar: resized price-30: debt direction | not asserted: the gearing cap binds | R0 → R-tariff-30 | 6769.603805 → 6883.275066 | NOT_ASSERTED |
| solar: resized hours-30: debt direction | not asserted: the gearing cap binds | R0 → R-hours-30 | 6769.603805 → 6724.968784 | NOT_ASSERTED |
| solar: resized combined downside: debt falls when DSCR capacity binds | re-sized debt quantum falls | R0 → R-combined | 6769.603805 → 6140.532576 | PASS |
| solar: R-hours-30: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-hours-30 | 0 → 0.000000 | PASS |
| solar: R-tariff-30: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-tariff-30 | 0 → -0.000000 | PASS |
| solar: R-combined: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-combined | 0 → 0.000000 | PASS |
| solar: R-rate-6.5: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-rate-6.5 | 0 → 0.000000 | PASS |
| solar: R-opex+50: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → R-opex+50 | 0 → 0.000000 | PASS |
| solar: L-P90: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | R0 → L-P90 | 0 → -0.000000 | PASS |
| solar: resized capex+10 raises uses and equity | equity funding rises | R0 → R-capex+10 | 2256.534602 → 2470.848722 | PASS |
| solar: resized opex+50 lowers EBITDA | EBITDA falls | R0 → R-opex+50 | 36953.633862 → 35439.872707 | PASS |
| solar: resized rate control | explicit 5.50% schedule equals the default case | R0 → R-rate-5.5 | 6769.603805 → 6769.603805 | PASS |
| solar: resized rate+100bp raises interest | total interest rises | R-rate-5.5 → R-rate-6.5 | 2186.291739 → 2778.245586 | PASS |
| solar: resized combined downside lowers EBITDA | EBITDA falls | R0 → R-combined | 36953.633862 → 26250.543903 | PASS |
| solar: resized tenor 10 vs 18 debt capacity | a longer tenor does not reduce debt capacity | R-tenor-10 → R-tenor-18 | 6583.298481 → 6769.603805 | PASS |
| solar: R0 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R0 | 1.200000 → 1.200000 | PASS |
| solar: R-hours-30 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-hours-30 | 1.200000 → 1.200000 | PASS |
| solar: R-tariff-30 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-tariff-30 | 1.200000 → 1.200000 | PASS |
| solar: R-capex+10 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-capex+10 | 1.200000 → 1.200000 | PASS |
| solar: R-opex+50 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-opex+50 | 1.200000 → 1.200000 | PASS |
| solar: R-rate-6.5 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-rate-6.5 | 1.200000 → 1.200000 | PASS |
| solar: R-combined sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-combined | 1.200000 → 1.200000 | PASS |
| solar: R-tenor-10 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-tenor-10 | 1.200000 → 1.200000 | PASS |
| solar: R-tenor-18 sizing DSCR holds the target | minimum sizing DSCR is not below the sizing target (constraint satisfied) | target → R-tenor-18 | 1.200000 → 1.200000 | PASS |
| solar: P90 lender case does not enlarge debt | P90 debt quantum is not above P50 | R0 → L-P90 | 6769.603805 → 6731.465445 | PASS |
| solar: lender case leaves the operating case unchanged | EBITDA identical under P50 and P90 lender cases | R0 → L-P90 | 36953.633862 → 36953.633862 | PASS |
| solar: P90 keeps base coverage at or above P50 | base minimum DSCR not below P50 case | R0 → L-P90 | 1.200000 → 1.275620 | PASS |
| solar: P90 + price-10 lowers EBITDA | EBITDA falls | L-P90 → L-P90-price-10 | 36953.633862 → 35640.287448 | PASS |
| solar: P90 + price-10: debt direction | not asserted: the gearing cap binds | L-P90 → L-P90-price-10 | 6731.465445 → 6820.955347 | NOT_ASSERTED |
| solar: L-P90-price-10: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | L-P90 → L-P90-price-10 | 0 → 0.000000 | PASS |
| solar: L-P90-rate-6.5: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | L-P90 → L-P90-rate-6.5 | 0 → 0.000000 | PASS |
| solar: L-downside: uses change explained by financing items (+CAPEX) | change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained | L-P90 → L-downside | 0 → 0.000000 | PASS |
| solar: P90 + rate+100bp raises interest | total interest rises | L-P90 → L-P90-rate-6.5 | 2449.694369 → 3225.168925 | PASS |
| solar: lender combined downside lowers EBITDA | EBITDA falls | L-P90 → L-downside | 36953.633862 → 35640.287448 | PASS |

## Cases without a committed Run

* `solar-Z-price-85` — contracted price -85% (near-zero CFADS): These inputs leave part of the shareholder loan unpaid at its maturity, so the model did not produce a result. Review OPEX, CAPEX, revenue or shareholder-loan terms and run again. Your edits are saved; the previous Last Run is unchanged.
* `solar-Z-price-98` — contracted price -98% (CFADS below debt service): The model&#39;s integrity checks stopped this run for the current inputs, so no result was produced. Review your recent changes and run again. Your edits are saved; the previous Last Run is unchanged.
