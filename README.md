## Setup

1. `python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt && playwright install chromium`
3. Copy `.env.example` to `.env`
```bash
   cp .env.example .env
```
4. Then your `.env` file should look like this:
```
ANTHROPIC_API_KEY=
#PARABANK_BASE_URL=https://parabank.parasoft.com/parabank
PARABANK_BASE_URL=http://localhost:8080
PARABANK_USERNAME=john
PARABANK_PASSWORD=demo
```
Add `ANTHROPIC_API_KEY` with your own.

## Running ParaBank locally with Docker (recommended)
The public ParaBank `parabank.parasoft.com` is a shared sandbox that resets periodically and can return server-side errors unrelated to this project. For reliable, reproducible runs, I would recommend using a local Docker instance

1. Start the container:
```bash
   docker compose up -d
```
2. Wait ~10s for Tomcat to boot, then initialize the database:
```bash
   curl -s -L http://localhost:8080/parabank/initializeDB.htm > /dev/null
```
3. Register a test user in a browser: `http://localhost:8080/parabank/register.htm`. Alternatively, you can use the default username and login provided in `.env.example`

4. In case you want to use your own credentials. In `.env`, set:
```bash
   PARABANK_BASE_URL=http://localhost:8080
   PARABANK_USERNAME=<the username you just registered>
   PARABANK_PASSWORD=<the password you just registered>
```

>Note: registered username and password will not work in the production app `parabank.parasoft.com` if you want to use your own credentials, so I would recommend going by the ones provided in the `.env.example`*


## Demo path

### 1. Discovery: 
The loan capability replays the login capability first (auth_capability_id in capabilities/loan.yaml), so record the login first.

1.1 To create an LLM discovery artifact and evidence to log in
```bash
python -m src.cli discover --config capabilities/login.yaml
```

1.2 To create an LLM discovery artifact and evidence of requesting loan
```bash
python -m src.cli discover --config capabilities/loan.yaml
```

In the `/artifacts/` folder, you should see new populated artifacts with new versions.

### 2. Replay: scenarios
2.1 Success outcome: login succeeded
```
python -m src.cli replay --config capabilities/login.yaml --inputs "username=john,password=demo"
```

2.2 Business outcome: Wrong password 
```
python -m src.cli replay --config capabilities/login.yaml --inputs "username=john,password=wrong"
```


2.3 Success outcome: Loan Approved

Type resume and enter the note
```
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"
```


2.4 Business outcome: Loan Denied

Type resume and enter the note
```
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=100000,down_payment=1,from_account_id=13344"
```

2.5 Failure outcome: Account does not exist

Type resume and enter the note, then abort
```
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=99999"
```


2.6 Failure outcome: aborting the loan request

Abort at the first prompt
```
python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"
```



## Evidence
Each run writes to its own folder under `/evidence/`:
- `discovery_<capability>_<time>_<run_id>/`: the agent's full transcript (result.json, credentials redacted) and a screenshot of every step.
- `replay_<capability>_<time>_<run_id>/`: the result (result.json: status, outputs, failed step, expected vs. observed, escalations) and a screenshot for each escalation.
