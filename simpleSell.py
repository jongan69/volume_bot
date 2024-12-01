import asyncio
import datetime
import time
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.commitment import Confirmed, Finalized, Commitment
from solana.rpc.api import RPCException
from solana.rpc.api import Client
from solders.compute_budget import set_compute_unit_price,set_compute_unit_limit
from solders.transaction import Transaction
from spl.token.instructions import CloseAccountParams, close_account
from createCloseAccount import fetch_pool_keys, get_token_account, make_swap_instruction , sell_get_token_account
from walletTradingFunctions.dexscreener import getSymbol
from solana.transaction import Transaction
from spl.token.constants import WRAPPED_SOL_MINT
from dotenv import load_dotenv
import os
import traceback

load_dotenv()
RPC_HTTPS_URL = (os.getenv("RPC_HTTPS_URL"))
solana_client = Client(RPC_HTTPS_URL)

LAMPORTS_PER_SOL = 1000000000
MAX_RETRIES = 5
RETRY_DELAY = 3


def getTimestamp():
    while True:
        timeStampData = datetime.datetime.now()
        currentTimeStamp = "[" + timeStampData.strftime("%H:%M:%S.%f")[:-3] + "]"
        return currentTimeStamp

async def sell(PAYER, TOKEN_TO_SWAP_SELL, amount_to_sell):
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            
            mint = Pubkey.from_string(TOKEN_TO_SWAP_SELL)
            sol = WRAPPED_SOL_MINT
            TOKEN_PROGRAM_ID = solana_client.get_account_info_json_parsed(mint).value.owner
            pool_keys = fetch_pool_keys(str(mint))
            
            if isinstance(pool_keys, str):
                print(f"Failed to fetch pool keys: {pool_keys}")
                return False

            accountProgramId = solana_client.get_account_info_json_parsed(mint)
            programid_of_token = accountProgramId.value.owner
            accounts = solana_client.get_token_accounts_by_owner_json_parsed(PAYER.pubkey(), TokenAccountOpts(
                program_id=programid_of_token)).value
            
            balance = 0  # Initialize balance with a default value
            for account in accounts:
                mint_in_acc = account.account.data.parsed['info']['mint']
                if mint_in_acc == str(mint):
                    balance = int(account.account.data.parsed['info']['tokenAmount']['amount'])
                    print("Your Token Balance is: ", balance)
                    break

            if balance == 0:
                print("No matching token account found or balance is zero.")
                return False

            if amount_to_sell is None:
                # sell entire balance
                amount_in = int(balance * LAMPORTS_PER_SOL)
            else:
                # sell specific amount
                amount_in = int(amount_to_sell * LAMPORTS_PER_SOL)

            print("Amount to sell:", amount_in)
            if amount_in > (balance * LAMPORTS_PER_SOL):
                print(f"Insufficient balance. You only have {balance} tokens")
                return False

            swap_token_account = sell_get_token_account(solana_client, PAYER.pubkey(), mint)
            WSOL_token_account, WSOL_token_account_Instructions = get_token_account(solana_client, PAYER.pubkey(), sol)
            print("Amount to sell:", amount_in)

            print("Create Swap Instructions...")
            instructions_swap = make_swap_instruction(amount_in,
                                                      swap_token_account,
                                                      WSOL_token_account,
                                                      pool_keys,
                                                      mint,
                                                      solana_client,
                                                      PAYER
                                                      )
            params = CloseAccountParams(account=WSOL_token_account, dest=PAYER.pubkey(), owner=PAYER.pubkey(),
                                        program_id=TOKEN_PROGRAM_ID)
            closeAcc = (close_account(params))
            swap_tx = Transaction()
            if WSOL_token_account_Instructions != None:
                recent_blockhash = solana_client.get_latest_blockhash(commitment="confirmed")
                swap_tx.recent_blockhash = recent_blockhash.value.blockhash
                swap_tx.add(WSOL_token_account_Instructions)

            swap_tx.add(instructions_swap, set_compute_unit_price(25_232), set_compute_unit_limit(200_337))
            swap_tx.add(closeAcc)

            txn = solana_client.send_transaction(swap_tx, PAYER)
            txid_string_sig = txn.value
            if txid_string_sig:
                print("Transaction sent")
                print("Waiting Confirmation")

            confirmation_resp = solana_client.confirm_transaction(
                txid_string_sig,
                commitment=Confirmed,
                sleep_seconds=0.5,
            )

            if confirmation_resp.value[0].err == None and str(
                    confirmation_resp.value[0].confirmation_status) == "TransactionConfirmationStatus.Confirmed":
                print("Transaction Confirmed")
                print(f"Transaction Signature: https://solscan.io/tx/{txid_string_sig}")

                return

            else:
                print("Transaction not confirmed")
                return False

        except asyncio.TimeoutError:
            print("Transaction confirmation timed out. Retrying...")
            retry_count += 1
            time.sleep(RETRY_DELAY)
        except RPCException as e:
            print(f"RPC Error: [{e.args[0].message}]... Retrying...")
            retry_count += 1
            time.sleep(RETRY_DELAY)
        except Exception as e:
            if retry_count ==MAX_RETRIES:
                print("Unhandled exception occurred:")
                traceback.print_exc()  # Print the full traceback
            if "block height exceeded" in str(e):
                print("Transaction has expired due to block height exceeded. Retrying...", e.args[0])
                retry_count += 1
                await asyncio.sleep(RETRY_DELAY)
            else:
                traceback.print_exc()  # Print the full traceback
                print(f"Unhandled exception: {e}. Retrying...")
                retry_count += 1
                await asyncio.sleep(RETRY_DELAY)

    print("Failed to confirm transaction after maximum retries.")
    return False