## Setup

1. Activate an environment
   * macOS:
      ```
      python3 -m venv .venv && source .venv/bin/activate
      ```
   * Windows:
     ```
     ```
3. Install dependencies
   ```
   pip install -r requirements.txt && playwright install chromium
   ```
5. Copy `.env.example` to `.env`
   ```bash
      cp .env.example .env
   ```
6. Then your `.env` file should look like this:
   ```
   ANTHROPIC_API_KEY=
   #PARABANK_BASE_URL=https://parabank.parasoft.com/parabank
   PARABANK_BASE_URL=http://localhost:8080
   PARABANK_USERNAME=john
   PARABANK_PASSWORD=demo
   ```
   Add your own anthropic key in `ANTHROPIC_API_KEY` 

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
3. Use the default user from `.env.example` (`john` / `demo`), which exists after the database reset in step 2. The loan replays below use account `13344`, one of this user's default accounts.

4. To use your own user instead, register at `http://localhost:8080/parabank/register.htm` and set in `.env`:
   ```bash
      PARABANK_USERNAME=<your username>
      PARABANK_PASSWORD=<your password>
   ```
   Then replace `13344` in the loan commands with an account number from your Accounts Overview page.

>Note: The registered username and password will not work in the production app `parabank.parasoft.com` if you want to use your own credentials, so I would recommend going by the ones provided in the `.env.example`*


## Running without live services
The project uses two live services: the Anthropic API (for the LLM agent) and ParaBank (the target app).
- **Without an Anthropic API key:** Discovery CLI commands cannot be run, but you can use existing `/artifacts/` to replay them deterministically.
- **Without ParaBank:** nothing can run, but the committed `/artifacts/` and `/evidence/` show every stage of a real run. The default setup runs ParaBank locally with Docker (`PARABANK_BASE_URL=http://localhost:8080`). To use the public site instead, set `PARABANK_BASE_URL=https://parabank.parasoft.com` and run discovery again: the committed artifacts contain `localhost` URLs, so they only replay against the local instance.
  
## Demo path

### 1. Discovery: 
The loan capability replays the login capability first (auth_capability_id in capabilities/loan.yaml), so record the login first.

* 1.1 To create an LLM discovery artifact and evidence to log in
   ```bash
   python -m src.cli discover --config capabilities/login.yaml
   ```

* 1.2 To create an LLM discovery artifact and evidence of requesting loan
   ```bash
   python -m src.cli discover --config capabilities/loan.yaml
   ```

In the `/artifacts/` folder, you should see new populated artifacts with new versions.

### 2. Replay: scenarios
* 2.1 Success outcome: login succeeded
   ```
   python -m src.cli replay --config capabilities/login.yaml --inputs "username=john,password=demo"
   ```
   Expected: Status: success, login_succeeded: true

* 2.2 Business outcome: Wrong password 
   ```
   python -m src.cli replay --config capabilities/login.yaml --inputs "username=john,password=wrong"
   ```
   Expected: Status: business_outcome, outcome_name: invalid_credentials


* 2.3 Success outcome: Loan Approved

   Type resume and enter the note
   ```
   python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"
   ```
   Expected: Status: success, loan_status: success, plus a new_account_id


* 2.4 Business outcome: Loan Denied

   Type resume and enter the note
   ```
   python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=100000,down_payment=1,from_account_id=13344"
   ```
   Expected: Status: business_outcome, loan_status: insufficient_funds

* 2.5 Failure outcome: Account does not exist

   Type resume and enter the note, then abort
   ```
   python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=99999"
   ```
   Expected: an escalation listing the real accounts, then Status: failure at step 3

* 2.6 Failure outcome: aborting the loan request

   Abort at the first prompt
   ```
   python -m src.cli replay --config capabilities/loan.yaml --inputs "amount=1000,down_payment=10,from_account_id=13344"
   ```
   Expected: Status: failure, "Replay aborted by operator…"


## Evidence
Each run writes to its own folder under `/evidence/`:
- `discovery_<capability>_<time>_<run_id>/`: the agent's full transcript (result.json, credentials redacted) and a screenshot of every step.
- `replay_<capability>_<time>_<run_id>/`: the result (result.json: status, outputs, failed step, expected vs. observed, escalations) and a screenshot for each escalation.
