import sqlite3

import openai
import hashlib
import time
import math
import re

openai.api_key = "your_openai_api_key"

model_name_to_max_token_limit = {
    "gpt-3.5-turbo": 4096,
    "text-davinci-003": 4096,
    "gpt-4": 8192
}


def count_tokens(text):
    return math.ceil(len(text) / 4)


def count_tokens_in_messages(messages):
    return count_tokens("\n\n".join([f"[{m['name']}]: {m['content']}" for m in messages]))


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def delay(seconds):
    time.sleep(seconds)


async def get_chat_completion(messages, model="gpt-3.5-turbo", temperature=0.7):
    response = openai.Completion.create(
        engine=model,
        prompt=messages,
        temperature=temperature,
        max_tokens=150,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )

    choice = response.choices[0]
    return choice.text.strip()


def compress_summary(summary, token_limit, model, on_progress):
    i = 0
    while count_tokens(summary) > token_limit:
        if on_progress:
            on_progress(f"compressing summary ({i})")

        messages = [
            {"role": "system",
             "content": '''You are a text compression assistant. 
             You respond only with summary that the user requests - 
             nothing more, nothing less.'''},
            {"role": "user",
             "content": f'''Please compress this text to 75% of its original size:
             \n\n---\n\n{summary}\n\n---\n\nTry to remove unimportant details and 
             make the wording more *concise* to save space. 
             DON'T MAKE IT TOO SHORT. Retain all important details.\n\n
             Please reply with the *slightly* shortened text - nothing else. 
             Keep *almost all* of the information.'''},
        ]

        new_summary = get_chat_completion(messages, model, temperature=0.7)
        if not new_summary:
            if on_progress:
                on_progress("error, retrying...")
            delay(3)
        else:
            summary = new_summary
            print(f"compressed summary ({count_tokens(summary)} tokens): {summary}")

        i += 1

    return summary


def get_original_messages(up_to_message_id=None):
    # Replace this with your database implementation to get original messages
    original_messages = get_messages_from_database()

    if up_to_message_id is None:
        up_to_message_id = original_messages[-1]['id']

    original_messages = [msg for msg in original_messages if msg['id'] <= up_to_message_id]
    return original_messages


def get_token_limit_for_summary_and_messages(character):
    token_limit = model_name_to_max_token_limit[character['model_version']]
    # TODO: let user set aiCharacter.tokenLimit (via oc.character.tokenLimit) here to override this if it's smaller
    #  than the model's max token limit
    token_limit -= round(token_limit * 0.1)  # buffer due to token count being an estimate
    token_limit -= count_tokens(character['system_message'])  # allow for system message tokens
    token_limit -= count_tokens(character.get('reminder_message', ''))  # allow for reminder message tokens
    token_limit -= round(token_limit * 0.2)  # allow for bot response
    return token_limit


def get_messages_from_database():
    connection = sqlite3.connect("conversation.db")
    cursor = connection.cursor()
    cursor.execute("SELECT id, content, character_id FROM messages")
    messages = [{"id": row[0], "content": row[1], "character_id": row[2]} for row in cursor.fetchall()]
    connection.close()
    return messages


async def compute_and_save_summary_if_needed(ai_character, user_character, up_to_message_id=None, on_progress=None):
    # Replace the following line with your database implementation to get original messages
    model = "gpt-3.5-turbo"
    original_messages = get_original_messages(up_to_message_id)

    remaining_messages = prepare_messages_for_bot(original_messages, ai_character, user_character)

    token_limit_for_summary_and_messages = get_token_limit_for_summary_and_messages(ai_character)
    max_token_count_of_summary = round(token_limit_for_summary_and_messages / 3)

    message_tokens_to_consume_per_summary = round(model_name_to_max_token_limit[model] * 0.3)

    # Check for token limit error
    if max_token_count_of_summary + message_tokens_to_consume_per_summary > model_name_to_max_token_limit[model] - 500:
        raise ValueError('''The specified values of `max_token_count_of_summary` 
        and `message_tokens_to_consume_per_summary` are 
        such that the summarization process could go over this model's token limit.''')

        initial_token_count = count_tokens_in_messages(remaining_messages)
        current_token_count = initial_token_count
        prev_summary = None
        prev_instruction_hash = None
        i = 0

        while current_token_count > token_limit_for_summary_and_messages:
            progress = 1 - ((current_token_count - token_limit_for_summary_and_messages) / (
                    initial_token_count - token_limit_for_summary_and_messages))
            if on_progress:
                on_progress(f"summarizing (step {i}, {round(progress * 100)}% done)")

            message_batch_token_count = 0
            message_batch_arr = []
            while message_batch_token_count < message_tokens_to_consume_per_summary:
                m = remaining_messages.pop(0)
                message_batch_arr.append(m)
                message_batch_token_count += count_tokens_in_messages([m])

            if i > 0:
                message_batch_text = "\n\n".join([f"[{m['name']}]: {m['content']}" for m in message_batch_arr])
                message_batch_summarization_instruction = f'''Here's what has recently 
                happened:\n\n---\n{message_batch_text}\n---\n\n
                Here's a summary of what happened previously:
                \n\n---\n{prev_summary}\n---\n\n
                Please reply with a new version of this summary that ALSO includes 
                what has recently happened. Include ALL the KEY details. 
                DO NOT MISS ANY IMPORTANT DETAILS. 
                You MUST include all the details that were in the previous summary 
                in your response. 
                Your response should start with \"{prev_summary.split(' ')[0:5]}\" and 
                it should compress all the important details into a new summary.'''

            else:
                message_batch_text = "\n\n".join([f"[{m['name']}]: {m['content']}" for m in message_batch_arr])
                message_batch_summarization_instruction = f'''Please summarize the content 
                of these messages:\n\n------\n{message_batch_text}\n------\n\nRespond 
                with the summary only - nothing else. Include all 
                relevant details. Be concise, but DO NOT leave out any important details.'''

            # Replace the following line with your database implementation to get the summary
            summary_obj = get_summary_from_db(prev_instruction_hash)
            summary = summary_obj.get("summary")

            if not summary:
                # Create summary
                while True:
                    summary = await get_chat_completion(
                        messages=[
                            {"role": "system",
                             "content": '''You are a text summarization assistant. 
                             You respond only with summary that the user requests - 
                             nothing more, nothing less.'''},
                            {"role": "user", "content": message_batch_summarization_instruction}
                        ],
                        model=model,
                        temperature=0.7
                    )

                    if summary:
                        break
                    if on_progress:
                        on_progress("error, retrying...")
                    await asyncio.sleep(3000)

                # Replace the following line with your database implementation to save the summary
                save_summary_to_db(summary_obj)

            if count_tokens(summary) > max_token_count_of_summary:
                summary = await compresssummary(summary, max_token_count_of_summary, model, on_progress)
            # Replace the following line with your database implementation to update the summary
            update_summary_in_db(summary_obj, summary)

        # Get the size difference between summary and original messages
        summary_token_change = count_tokens(prev_summary or "") - count_tokens(summary)
        message_arr_token_change = -message_batch_token_count
        overall_token_change = summary_token_change + message_arr_token_change
        current_token_count += overall_token_change

        prev_summary = summary
        prev_instruction_hash = summary_obj["hash"]
        i += 1

    # NOTE: prev_summary can be None - i.e., no summaries were needed to get messages under the
    # tokenLimitForSummaryAndMessages limit
    return {"summary": prev_summary, "instruction_hash": prev_instruction_hash,
            "remaining_messages": remaining_messages}


def prepare_messages_for_bot(messages, ai_character, user_character):
    messages = [m.copy() for m in messages if not ('hiddenFrom' in m and 'ai' in m['hiddenFrom'])]

    for m in messages:
        m['content'] = re.sub(r'<!--hidden-from-ai-start-->.*?<!--hidden-from-ai-end-->', '', m['content'],
                              flags=re.DOTALL)

    def get_role_and_name(character_id):
        if character_id == user_character['id']:
            return 'user', user_character['name'].replace(" ", "_")
        elif character_id == ai_character['id']:
            return 'assistant', ai_character['name'].replace(" ", "_")
        else:
            return 'system', 'system_name'

    prepared_messages = []
    for m in messages:
        role, name = get_role_and_name(m['character_id'])
        prepared_message = {
            'role': role,
            'content': m['content'],
            'name': name,
            'id': m['id']
        }
        prepared_messages.append(prepared_message)

    return prepared_messages
