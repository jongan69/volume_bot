import asyncio
import logging
import os
from birdeye import get_price
from simpleSell import sell
from simpleBuy import buy
import requests
import concurrent.futures
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

TokenCA = os.getenv("TOKENCA")
TokenCA2 = os.getenv("TOKENCA2")
SOLANA_MINT_ADDRESS = os.getenv("SOLANA_MINT_ADDRESS")
RPC_HTTPS_URL = os.getenv("RPC_HTTPS_URL_TESTNET")
PAYER = Keypair.from_base58_string(os.getenv("PrivateKey"))

async def sell_with_env_wallet(token_to_sell, amount):
    # Perform a normal sell transaction
    sell_transaction = await sell(PAYER, token_to_sell, amount)
    if sell_transaction is not False:
        logging.info(f"Sell Transaction Result: {sell_transaction}")
    else:
        logging.error(f"Failed to sell {amount} of mint {token_to_sell}")

    # Get the current price of the token in USD
    token_price = get_price(token_to_sell)
    if token_price is not None and sell_transaction is not False:
        # Calculate the total USD value of the sold amount
        total_usd_value = amount * token_price
        logging.info(f"Sold {amount} of {token_to_sell} for {total_usd_value}")
    else:
        logging.error(f"Failed to sell token {amount} of mint {token_to_sell}")

async def buy_with_env_wallet(token_to_buy, amount):
    # Perform a normal buy transaction
    buy_transaction = await buy(PAYER, token_to_buy, amount)
    if buy_transaction is not False:
        logging.info(f"Buy Transaction Result: {buy_transaction}")
    else:
        logging.error(f"Failed to buy {amount} of mint {token_to_buy}")

    print(buy_transaction)

async def check_balance_and_sell(token_to_sell, amount):
    # Check balance before selling
    balance = await get_balance(PAYER, token_to_sell)
    if balance < amount:
        logging.error(f"Insufficient balance to sell {amount} of {token_to_sell}. Current balance: {balance}")
        return False

    # Proceed with selling if balance is sufficient
    return await sell_with_env_wallet(token_to_sell, amount)

async def check_balance_and_buy(token_to_buy, amount):
    # Check SOL balance before buying
    sol_balance = get_sol_balance(PAYER.pubkey())
    required_amount = amount * get_price(token_to_buy)
    if sol_balance < required_amount:
        logging.error(f"Insufficient SOL balance to buy {amount} of {token_to_buy}. Required: {required_amount}, Current balance: {sol_balance}")
        return False

    # Proceed with buying if balance is sufficient
    return await buy_with_env_wallet(token_to_buy, amount)

# Function to make a synchronous HTTP request using requests
def get_balance_sync(token_account):
    url = RPC_HTTPS_URL
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            token_account, 
            {"encoding": "jsonParsed"}
        ]
    }

    response = requests.post(url, json=payload, headers=headers)
    print(response)
    if response.status_code == 200:
        data = response.json()
        account_info = data.get("result", {}).get("value", {})
        if account_info:
            token_data = account_info.get("data", {}).get("parsed", {}).get("info", {})
            amount = token_data.get("tokenAmount", {}).get("amount", "0")
            decimals = token_data.get("tokenAmount", {}).get("decimals", 0)
            # Convert the raw amount to a float using the decimals
            balance = int(amount) / (10 ** decimals)
            return balance
        else:
            logging.error(f"No account info found for {token_account}")
            return 0
    else:
        logging.error(f"Failed to get account info for {token_account}. HTTP Status: {response.status_code}")
        return 0

async def get_token_account_address(wallet_pubkey, token_mint_address):
    print(wallet_pubkey)
    print(token_mint_address)
    token_mint_pubkey = Pubkey.from_string(token_mint_address)
    token_account_pubkey = get_associated_token_address(wallet_pubkey, token_mint_pubkey)
    return str(token_account_pubkey)

async def get_balance(payer, token_account):
    token_account_address = await get_token_account_address(payer.pubkey(), token_account)
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        balance = await loop.run_in_executor(pool, get_balance_sync, token_account_address)
        logging.info(f"Balance: {balance}")
    return balance

def get_sol_balance(wallet_pubkey):
    url = RPC_HTTPS_URL
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [str(wallet_pubkey)]
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        balance_lamports = data.get("result", {}).get("value", 0)
        balance_sol = balance_lamports / 1_000_000_000  # Convert lamports to SOL
        return balance_sol
    else:
        logging.error(f"Failed to get SOL balance for {wallet_pubkey}. HTTP Status: {response.status_code}")
        return 0

async def volume_bot():
    iteration_count = 0
    reset_interval = 10  # Number of iterations before selling all tokens

    while True:
        # Define the tokens and amounts you want to trade
        tokens_to_trade = [
            {"token": TokenCA, "buy_amount_sol": 0.05},
            {"token": TokenCA2, "buy_amount_sol": 0.05}
            # Add more tokens as needed
        ]

        if iteration_count >= reset_interval:
            # Sell all token balances
            logging.info("Selling all token balances to start over.")
            for trade in tokens_to_trade:
                token = trade["token"]
                current_token_balance = await get_balance(PAYER, token)
                if current_token_balance > 0:
                    logging.info(f"Selling entire balance of {current_token_balance} for token {token}.")
                    await check_balance_and_sell(token, current_token_balance)
            iteration_count = 0  # Reset the counter after selling all tokens

        for trade in tokens_to_trade:
            token = trade["token"]
            buy_amount_sol = trade["buy_amount_sol"]

            # Check if there is enough SOL to perform the buy, ensuring 0.01 SOL is reserved for fees
            sol_balance = get_sol_balance(PAYER.pubkey())
            required_sol = buy_amount_sol + 0.01  # Reserve 0.01 SOL for transaction fees
            if sol_balance < required_sol:
                logging.warning(f"Insufficient SOL balance for buying {buy_amount_sol} SOL worth of {token}. Current balance: {sol_balance} SOL.")
                
                # Calculate the amount of tokens to sell to cover the shortfall
                token_price = get_price(token)
                if token_price is not None:
                    shortfall_sol = required_sol - sol_balance
                    sell_amount = shortfall_sol / token_price
                    logging.info(f"Selling {sell_amount} of {token} to cover the shortfall.")
                    
                    # Perform sell operation to cover the shortfall
                    await check_balance_and_sell(token, sell_amount)
                else:
                    logging.error(f"Failed to retrieve price for token {token}. Cannot sell to cover shortfall.")
                    continue  # Skip to the next token if price retrieval fails

            # Perform buy operation with balance check
            await check_balance_and_buy(token, buy_amount_sol)

            # Calculate the equivalent sell amount in CA tokens to cover the next buy
            next_token_price = get_price(token)
            if next_token_price is not None:
                # Calculate the sell amount needed to cover the next buy
                next_buy_amount_sol = buy_amount_sol  # Assuming the next buy amount is the same
                sell_amount = next_buy_amount_sol / next_token_price

                # Ensure the sell amount does not exceed the current token balance
                current_token_balance = await get_balance(PAYER, token)
                if sell_amount > current_token_balance:
                    sell_amount = current_token_balance
                    logging.info(f"Adjusted sell amount to {sell_amount} due to insufficient token balance.")

                logging.info(f"Selling {sell_amount} of {token} to cover the next buy.")
                # Perform sell operation with balance check
                await check_balance_and_sell(token, sell_amount)
            else:
                logging.error(f"Failed to retrieve price for token {token}")

        # Increment the iteration counter
        iteration_count += 1

        # Wait for 5 minutes before the next round of trades
        await asyncio.sleep(100)  # 300 seconds = 5 minutes

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(volume_bot())