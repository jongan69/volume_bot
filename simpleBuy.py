import asyncio
import datetime
import os
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from solana.rpc.commitment import Commitment, Confirmed, Finalized
from solana.rpc.api import RPCException
from solana.rpc.api import Client, Keypair
from solana.rpc.async_api import AsyncClient
from solders.compute_budget import set_compute_unit_price,set_compute_unit_limit
from spl.token.instructions import create_associated_token_account, get_associated_token_address, close_account, \
    CloseAccountParams
from createCloseAccount import  fetch_pool_keys,  make_swap_instruction
from spl.token.client import Token
from spl.token.core import _TokenCore
import traceback
from dotenv import load_dotenv

load_dotenv()

async_solana_client= AsyncClient(os.getenv("RPC_HTTPS_URL")) #Enter your API KEY in .env file
solana_client = Client(os.getenv("RPC_HTTPS_URL"))

LAMPORTS_PER_SOL = 1000000000
MAX_RETRIES = 5
RETRY_DELAY = 3

#You can use getTimeStamp With Print Statments to evaluate How fast your transactions are confirmed

def getTimestamp():
    while True:
        timeStampData = datetime.datetime.now()
        currentTimeStamp = "[" + timeStampData.strftime("%H:%M:%S.%f")[:-3] + "]"
        return currentTimeStamp


async def get_token_account(ctx,
                                owner: Pubkey.from_string,
                                mint: Pubkey.from_string):
        try:
            account_data = await ctx.get_token_accounts_by_owner(owner, TokenAccountOpts(mint))
            return account_data.value[0].pubkey, None
        except:
            swap_associated_token_address = get_associated_token_address(owner, mint)
            swap_token_account_Instructions = create_associated_token_account(owner, owner, mint)
            return swap_associated_token_address, swap_token_account_Instructions

async def buy(PAYER, TOKEN_TO_SWAP_BUY, amount):
    retry_count = 0
    max_retries = 10  # Increase the number of retries
    while retry_count < max_retries:
        try:
            # token_symbol, SOl_Symbol = getSymbol(TOKEN_TO_SWAP_BUY)
            mint = Pubkey.from_string(TOKEN_TO_SWAP_BUY)
            pool_keys = fetch_pool_keys(str(mint))
            amount_in = int(amount * LAMPORTS_PER_SOL)
            accountProgramId = solana_client.get_account_info_json_parsed(mint)
            TOKEN_PROGRAM_ID = accountProgramId.value.owner

            balance_needed = Token.get_min_balance_rent_for_exempt_for_account(solana_client)
            swap_associated_token_address, swap_token_account_Instructions = await get_token_account(async_solana_client,PAYER.pubkey(),mint)
            WSOL_token_account, swap_tx, PAYER, Wsol_account_keyPair, opts, = _TokenCore._create_wrapped_native_account_args(
                TOKEN_PROGRAM_ID, PAYER.pubkey(), PAYER, amount_in,
                False, balance_needed, Commitment("confirmed"))

            instructions_swap = make_swap_instruction(amount_in,
                                                      WSOL_token_account,
                                                      swap_associated_token_address,
                                                      pool_keys,
                                                      mint,
                                                      solana_client,
                                                      PAYER)
            if instructions_swap is None:
                print("Failed to create swap instructions")
                return False
            params = CloseAccountParams(account=WSOL_token_account, dest=PAYER.pubkey(), owner=PAYER.pubkey(),
                                        program_id=TOKEN_PROGRAM_ID)
            closeAcc = (close_account(params))
            if swap_token_account_Instructions != None:
                swap_tx.add(swap_token_account_Instructions)

            # Check if the payer has enough balance
            payer_balance = solana_client.get_balance(PAYER.pubkey()).value
            if payer_balance < amount_in:
                print(f"Insufficient balance: {payer_balance} lamports, need {amount_in} lamports.")
                return False

            # Dynamic fee adjustment (example values, adjust as needed)
            compute_unit_price = 30_000  # Adjust based on network conditions
            compute_unit_limit = 250_000  # Adjust based on network conditions

            swap_tx.add(instructions_swap, set_compute_unit_price(compute_unit_price), set_compute_unit_limit(compute_unit_limit), closeAcc)
            txn = solana_client.send_transaction(swap_tx, PAYER, Wsol_account_keyPair)
            txid_string_sig = txn.value
            if txid_string_sig:
                print("Transaction sent")
                print("Waiting Confirmation")

            confirmation_resp = solana_client.confirm_transaction(
                txid_string_sig,
                commitment=Confirmed,
                sleep_seconds=0.5,
            )

            if confirmation_resp.value[0].err is None and str(
                    confirmation_resp.value[0].confirmation_status) == "TransactionConfirmationStatus.Confirmed":
                print("Transaction Confirmed")
                print(f"Transaction Signature: https://solscan.io/tx/{txid_string_sig}")
                return True

            else:
                print("Transaction not confirmed")
                retry_count += 1
                await asyncio.sleep(RETRY_DELAY)

        except asyncio.TimeoutError:
            print("Transaction confirmation timed out. Retrying...")
            retry_count += 1
            await asyncio.sleep(RETRY_DELAY)
        except RPCException as e:
            print(f"RPC Error: [{e.args[0]}]... Retrying...")
            retry_count += 1
            await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            if retry_count == max_retries:
                print("Max retries reached. Sending error to Telegram.")
                traceback.print_exc()  # Print the full traceback
            if "block height exceeded" in str(e):
                print("Transaction has expired due to block height exceeded. Retrying...")
                retry_count += 1
                await asyncio.sleep(RETRY_DELAY)
            else:
                traceback.print_exc()  # Print the full traceback
                print(f"Unhandled exception: {e}. Retrying...")
                retry_count += 1
                await asyncio.sleep(RETRY_DELAY)

    print("Failed to confirm transaction after maximum retries.")
    return False