## Setup

1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt && playwright install chromium`
3.  `touch .env`, then copy `.env.example` to `.env`, add your `ANTHROPIC_API_KEY`.
   

   
## Setting up locally with Docker

1. `docker compose up -d`
2. Wait ~10s for Tomcat to boot, then initialize the database:
   `curl -s -L http://localhost:8080/parabank/initializeDB.htm > /dev/null`
3. Register a test user once, in a browser: `http://localhost:8080/parabank/register.htm`
4. Set `PARABANK_BASE_URL=http://localhost:8080` in `.env`, matching the username/password you registered in `capabilities/login.yaml`'s `params` and `capabilities/loan.yaml`'s `auth_inputs`.


## Run

To create a LLM discory artifact and evidence to login
```bash
python -m src.cli discover --config capabilities/login.yaml
```

To create a LLM discory artifact and evidence to login
```bash
python -m src.cli discover --config capabilities/loan.yaml
```

To run successful deterministic replay 
```bash
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"
```

To run determinisctic buisness outcome replay, because of insuficient balance
```bash
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=100000,down_payment=90000,from_account_id=13344"
```

To run determiniscit failing outcome, because of non-existing account
```bash
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=99999"
```