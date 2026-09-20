## Setup

1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt && playwright install chromium`
3. Copy `.env.example` to `.env`
```bash
   cp .env.example .env
```
   

## Running ParaBank locally with Docker (recommended)
The public ParaBank `parabank.parasoft.com` is a shared sandbox that resets periodically and can return server-side errors unrelated to this project. For reliable, reproducible runs, I would recomend using a local Docker instance

1. Start the container:
```bash
   docker compose up -d
```
2. Wait ~10s for Tomcat to boot, then initialize the database:
```bash
   curl -s -L http://localhost:8080/parabank/initializeDB.htm > /dev/null
```
3. Register a test user, in a browser: `http://localhost:8080/parabank/register.htm`. Alternatively, you can use the default username and login provided from `.env.example`

4. In case if you wan to use own credentials. In `.env`, set:
```bash
   PARABANK_BASE_URL=http://localhost:8080
   PARABANK_USERNAME=<the username you just registered>
   PARABANK_PASSWORD=<the password you just registered>
```

*Note: registered username and password will not work in the production app `parabank.parasoft.com` if you want to use own credentials, so I would recomend going by the ones provided in the `.env.example`


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