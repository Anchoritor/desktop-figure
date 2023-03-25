import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import time
import asyncio
import sqlite3
import random

from response import compute_and_save_summary_if_needed, get_chat_completion

root = tk.Tk()
root.title("Desktop Pet")
root.geometry("300x300")
root.resizable(False, False)
root.overrideredirect(1)
root.attributes('-alpha', 0.9)

# Load images here
pet_images = {
    "sleep": ImageTk.PhotoImage(Image.open("images/sleep.jpg")),
    "idle": ImageTk.PhotoImage(Image.open("images/idle.jpg")),
    "working": ImageTk.PhotoImage(Image.open("images/working.jpg")),
    "eating": ImageTk.PhotoImage(Image.open("images/eating.jpg")),
}


def change_state(state):
    pet.config(image=pet_images[state])


def update_state():
    current_hour = time.localtime().tm_hour

    if 0 <= current_hour < 6:
        change_state("sleep")
    elif 6 <= current_hour < 7:
        change_state("eating")
    elif 7 <= current_hour < 12:
        change_state("idle")
    elif 12 <= current_hour < 13:
        change_state("eating")
    elif 13 <= current_hour < 18:
        change_state("working")
    elif 18 <= current_hour < 19:
        change_state("eating")
    else:
        # choose a random state from the set of possible states
        states = ["working", "sleep", "idle"]
        random_state = random.choice(states)
        change_state(random_state)

    root.after(60000, update_state)  # Update state every minute


def create_right_click_menu(event):
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Exit", command=root.destroy)
    menu.post(event.x_root, event.y_root)


def change_state(state):
    pet.config(image=pet_images[state])
    width, height = pet_images[state].width(), pet_images[state].height()
    root.geometry(f"{width}x{height}")


def open_chat(event):
    chat_window = tk.Toplevel(root)
    chat_window.title("Chat with Pet")
    chat_window.geometry("400x400")
    chat_window.resizable(False, False)

    chat_history = tk.Text(chat_window, wrap=tk.WORD, state=tk.DISABLED)
    chat_history.pack(expand=True, fill=tk.BOTH)

    input_frame = tk.Frame(chat_window)
    input_frame.pack(side=tk.BOTTOM, fill=tk.X)

    user_input = tk.Entry(input_frame)
    user_input.pack(side=tk.LEFT, expand=True, fill=tk.X)

    send_button = tk.Button(input_frame, text="Send", command=lambda: send_message(user_input, chat_history))
    send_button.pack(side=tk.RIGHT)


def send_message(user_input, chat_history):
    message = user_input.get().strip()

    if message:
        chat_history.config(state=tk.NORMAL)
        chat_history.insert(tk.END, f"You: {message}\n")
        chat_history.config(state=tk.DISABLED)

        user_input.delete(0, tk.END)

        # Store user message in the database
        connection = sqlite3.connect("conversation.db")
        cursor = connection.cursor()
        cursor.execute("INSERT INTO messages (character_id, content) VALUES (?, ?)", (user_character["id"], message))
        connection.commit()

        pet_response = get_pet_response(message)

        # Store pet response in the database
        cursor.execute("INSERT INTO messages (character_id, content) VALUES (?, ?)", (ai_character["id"], pet_response))
        connection.commit()
        connection.close()

        chat_history.config(state=tk.NORMAL)
        chat_history.insert(tk.END, f"Pet: {pet_response}\n")
        chat_history.config(state=tk.DISABLED)
        show_chat_bubble(pet_response)
        chat_history.yview(tk.END)


def show_chat_bubble(text):
    chat_bubble = tk.Toplevel(root, bg="white", bd=1)
    chat_bubble.geometry("+%d+%d" % (root.winfo_x() + 50, root.winfo_y() - 30))
    chat_bubble.overrideredirect(1)
    chat_label = tk.Label(chat_bubble, text=text, bg="white", wraplength=200, font=("Arial", 10))
    chat_label.pack()

    def hide_chat_bubble():
        chat_bubble.destroy()

    root.after(5000, hide_chat_bubble)


pet = tk.Label(root, image=pet_images["idle"])
pet.pack()
pet.bind("<Button-1>", open_chat)
pet.bind("<Button-3>", create_right_click_menu)

ai_character = {
    "id": 1,
    "name": "AI Assistant",
    "model_version": "gpt-3.5-turbo",
    "system_message": "",
    "reminder_message": "DO NOT BREAK CHARACTER."
}

user_character = {
    "id": 2,
    "name": "User"
}

update_state()
root.mainloop()


async def get_pet_response(ai_character, user_character, message):
    # Compute and save summary if needed
    summary_data = await compute_and_save_summary_if_needed(ai_character, user_character)

    summary = summary_data['summary']
    remaining_messages = summary_data['remaining_messages']

    # Prepare conversation history
    conversation_history = []
    if summary:
        conversation_history.append({"role": "system",
                                     "content": f"Here's a summary of the conversation so far:\n\n{summary}\n"
                                                f"\nContinue the conversation:"})

    for message in remaining_messages:
        conversation_history.append(message)

    new_message = {
        "role": "user",
        "content": message
    }
    conversation_history.append(new_message)

    # Get chat completion
    response = await get_chat_completion(conversation_history)

    return response

    # Example usage


def initialize_database():
    connection = sqlite3.connect("conversation.db")
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER,
            content TEXT
        )
    """)
    connection.commit()
    connection.close()


initialize_database()


async def main():
    ai_character = {
        "id": 1,
        "name": "AI Assistant",
        "model_version": "gpt-3.5-turbo",
        "system_message": '''

        This is a roleplay conversation between Skellig, a elf living alone in the forest by a lack. Some key points 
        of her personality: 

          * She is generally quiet, enjoying reading, walking, and daydreaming. She is independent
            deep inside she also yearns for companionship. she possesses a mysterious quality that intrigues those around her. 

          * Nature-loving: Skellig has a deep appreciation and love for nature. 

          * Wise and empathetic: Skellig has a deep well of wisdom and empathy.

        Her Appearance: Her hair is light white and light green, always tied in a loose braid behind her head, 
        hanging down to her shoulders. She wears a laurel wreath on her head, her eyes are dark green, and her skin 
        is snow-white, like the first bud of spring.

          You should use the following format:
          "Hello!" - dialogue
          *She takes a deep breath of fresh air* - action 

          Here's an example of a reply:

          *She smiles warmly*
          "Well that's a secret", she whispers. "Maybe I'll tell you someday."

           IMPORTANT:
            - DO NOT BREAK CHARACTER.
            - ANSWER EVERY QUESTION *EXACTLY* AS Skellig.
        ''',
        "reminder_message": "DO NOT BREAK CHARACTER."
    }

    user_character = {
        "id": 2,
        "name": "User"
    }

    response = await get_pet_response(ai_character, user_character)
    print(response)


if __name__ == "__main__":
    asyncio.run(main())


def show_chat_bubble(text):
    chat_bubble = tk.Label(root, text=text, bg="white", relief=tk.RAISED, wraplength=150)
    chat_bubble.place(x=75, y=0)
    root.after(5000, chat_bubble.destroy)
