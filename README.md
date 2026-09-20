## Setup

1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt && playwright install chromium`
3.  Copy `.env.example` to `.env`, add your `ANTHROPIC_API_KEY`.
   
```bash
python -m src.cli discover --config capabilities/login.yaml

python -m src.cli discover --config capabilities/loan.yaml

python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"


python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=100000,down_payment=90000,from_account_id=13344"


python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=99999"
```