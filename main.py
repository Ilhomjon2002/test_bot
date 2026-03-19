import json
import asyncio
import random
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, PollAnswerHandler, CallbackQueryHandler, CallbackContext
import os
import signal
import atexit
from datetime import datetime
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging settings
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is missing in the backend environment layout string!")

user_data = {}  # {chat_id: {...}}
quiz_catalog = {"B1": []}

def load_quiz_files(directory="quizzes"):
    global quiz_catalog
    quiz_catalog = {"B1": []}
    sections = ["B1"]
    
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    for section in sections:
        section_dir = os.path.join(directory, section)
        if not os.path.exists(section_dir):
            os.makedirs(section_dir)
        
        for file_name in os.listdir(section_dir):
            if file_name.endswith(".json"):
                file_path = os.path.join(section_dir, file_name)
                try:
                    with open(file_path, "r", encoding="utf-8") as file:
                        quiz_data = json.load(file)
                        if "name" in quiz_data and "questions" in quiz_data:
                            quiz_data["section"] = section
                            quiz_catalog[section].append(quiz_data)
                except (json.JSONDecodeError, FileNotFoundError) as error:
                    logger.error(f"Error reading file {section}/{file_name}: {error}")

async def set_bot_commands(bot):
    commands = [
        BotCommand("start", "Start the quiz"),
        BotCommand("restart", "Restart the quiz"),
        BotCommand("stop", "Stop the quiz"),
        BotCommand("quizlist", "Quiz list"),
        BotCommand("ranking", "View ranking")
    ]
    await bot.set_my_commands(commands)

async def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    logger.info(f"Start command: chat_id={chat_id}, user_id={user_id}")

    if update.message.chat.type in ["group", "supergroup"]:
        admins = await context.bot.get_chat_administrators(chat_id)
        if user_id not in [admin.user.id for admin in admins]:
            await update.message.reply_text("Only group admins can start the quiz!")
            return

    load_quiz_files()
    if not any(quiz_catalog[section] for section in quiz_catalog):
        await update.message.reply_text("Error! No quiz files found.")
        return

    if chat_id in user_data:
        await update.message.reply_text("A quiz is already running in this group. Use /stop to stop or /restart to restart.")
        return

    if context.args and len(context.args) > 0 and context.args[0].startswith("quiz_"):
        try:
            quiz_idx = int(context.args[0].split("_")[1])
            section = context.args[0].split("_")[2]
            await show_range_selection(update, context, chat_id, section, quiz_idx)
            return
        except (IndexError, ValueError):
            pass

    await show_sections(update, context, chat_id)

async def view_quiz_list(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    logger.info(f"Quizlist command: chat_id={chat_id}")
    await show_sections(update, context, chat_id)

async def show_sections(update: Update, context: CallbackContext, chat_id: int) -> None:
    load_quiz_files()
    keyboard = [
        [InlineKeyboardButton("B1", callback_data="section_B1")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, "Select one of the sections below:", reply_markup=reply_markup)

async def show_quizzes_in_section(update: Update, context: CallbackContext, chat_id: int, section: str) -> None:
    load_quiz_files()
    if not quiz_catalog[section]:
        await context.bot.send_message(chat_id, f"No quizzes found in section {section}.")
        return

    keyboard = []
    for idx, quiz in enumerate(quiz_catalog[section]):
        keyboard.append([
            InlineKeyboardButton(f"📖 {quiz['name']}", callback_data=f"select_quiz_{idx}_{section}"),
            InlineKeyboardButton("📤 Share", switch_inline_query=f"Quiz: {quiz['name']} - https://t.me/{context.bot.username}?start=quiz_{idx}_{section}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, f"Select a quiz from section {section}:", reply_markup=reply_markup)

async def show_range_selection(update: Update, context: CallbackContext, chat_id: int, section: str, quiz_idx: int) -> None:
    if section not in quiz_catalog or quiz_idx >= len(quiz_catalog[section]):
        await context.bot.send_message(chat_id, "Error! Selected quiz not found.")
        return

    quiz_data = quiz_catalog[section][quiz_idx]
    total_questions = len(quiz_data["questions"])

    ranges = []
    step = 30  # Following original code step=30
    for start in range(0, total_questions, step):
        end = min(start + step, total_questions)
        ranges.append((start, end))

    if not ranges:
        await context.bot.send_message(chat_id, "Error! Not enough questions in this quiz.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{start + 1}-{end}", callback_data=f"start_quiz_{quiz_idx}_{section}_{start}_{end}")]
        for start, end in ranges
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, f"Select a question range for {quiz_data['name']} (split by {step}):", reply_markup=reply_markup)

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"Button pressed: chat_id={chat_id}, data={data}")

    if data.startswith("section_"):
        section = data.split("_")[1]
        await show_quizzes_in_section(update, context, chat_id, section)
    elif data.startswith("select_quiz_"):
        parts = data.split("_")
        quiz_idx = int(parts[2])
        section = parts[3]
        await show_range_selection(update, context, chat_id, section, quiz_idx)
    elif data.startswith("start_quiz_"):
        parts = data.split("_")
        quiz_idx = int(parts[2])
        section = parts[3]
        start_idx = int(parts[4])
        end_idx = int(parts[5])
        await send_quiz_questions(update, context, chat_id, section, quiz_idx, start_idx, end_idx)
    elif data == "restart_quiz":
        await restart_quiz(update, context)
    elif data == "stop_quiz":
        await stop_quiz(update, context)

async def restart_quiz(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info(f"Restart command: chat_id={chat_id}")
    if chat_id not in user_data:
        await context.bot.send_message(chat_id, "No active quiz right now. Use /start to begin.")
        return

    section = user_data[chat_id]["section"]
    quiz_idx = user_data[chat_id]["quiz_idx"]
    start_idx = user_data[chat_id]["start_idx"]
    end_idx = user_data[chat_id]["end_idx"]
    await clear_tasks(chat_id)
    del user_data[chat_id]
    await send_quiz_questions(update, context, chat_id, section, quiz_idx, start_idx, end_idx)
    await context.bot.send_message(chat_id, "Quiz restarted!")

async def stop_quiz(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info(f"Stop command: chat_id={chat_id}")
    if chat_id not in user_data:
        await context.bot.send_message(chat_id, "No active quiz right now.")
        return

    await finish_quiz(update, context, chat_id)
    await context.bot.send_message(chat_id, "Quiz stopped!")

async def send_quiz_questions(update: Update, context: CallbackContext, chat_id: int, section: str, quiz_idx: int, start_idx: int, end_idx: int) -> None:
    if section not in quiz_catalog or quiz_idx >= len(quiz_catalog[section]):
        await context.bot.send_message(chat_id, "Error! Selected quiz not found.")
        logger.error(f"Quiz loading error: section={section}, quiz_idx={quiz_idx}")
        return

    quiz_data = quiz_catalog[section][quiz_idx]
    total_questions = len(quiz_data["questions"])
    if start_idx >= total_questions or end_idx > total_questions or start_idx >= end_idx:
        await context.bot.send_message(chat_id, "Error! Invalid range selected.")
        logger.error(f"Invalid range: start_idx={start_idx}, end_idx={end_idx}, total_questions={total_questions}")
        return

    await context.bot.send_message(chat_id, f"📌 Starting quiz {quiz_data['name']}! (Questions {start_idx + 1}-{end_idx})")
    logger.info(f"Quiz started: chat_id={chat_id}, section={section}, quiz_idx={quiz_idx}")

    questions = quiz_data["questions"][start_idx:end_idx].copy()
    random.shuffle(questions)

    user_data[chat_id] = {
        "section": section,
        "quiz_idx": quiz_idx,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "questions": questions,
        "current_question": 0,
        "poll_messages": {},
        "correct_option_ids": {},
        "users": {},
        "current_section_quizzes": quiz_catalog[section],
        "current_quiz_idx": quiz_idx,
        "is_running": True
    }

    await send_next_question(update, context, chat_id)

async def send_next_question(update: Update, context: CallbackContext, chat_id: int) -> None:
    if chat_id not in user_data or not user_data[chat_id].get("is_running", False):
        logger.warning(f"Quiz process stopped or missing: chat_id={chat_id}")
        return

    data = user_data[chat_id]
    if data["current_question"] < len(data["questions"]):
        question = data["questions"][data["current_question"]]
        wait_time = question.get("time", 10)  # Time is just for display
        logger.info(f"New question: chat_id={chat_id}, question_idx={data['current_question']}, time={wait_time}")

        options = question["answers"].copy()
        correct_answer_idx = question["correct_answer"]
        original_correct_text = question["answers"][correct_answer_idx]
        random.shuffle(options)
        new_correct_option_id = options.index(original_correct_text)

        try:
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=question["question"],
                options=options,
                type=Poll.QUIZ,
                correct_option_id=new_correct_option_id,
                is_anonymous=False,
                open_period=wait_time
            )
            data["poll_messages"][poll_message.poll.id] = data["current_question"]
            data["correct_option_ids"][poll_message.poll.id] = new_correct_option_id
            data["start_time"] = datetime.now()
        except Exception as e:
            logger.error(f"Error sending poll: chat_id={chat_id}, error={e}")
            return
    else:
        # Questions finished, show results
        await finish_quiz(update, context, chat_id)

async def move_to_next_quiz(update: Update, context: CallbackContext, chat_id: int):
    if chat_id not in user_data or not user_data[chat_id].get("is_running", False):
        logger.warning(f"Could not find data to move to next quiz: chat_id={chat_id}")
        return

    data = user_data[chat_id]
    data["current_quiz_idx"] += 1

    if data["current_quiz_idx"] < len(data["current_section_quizzes"]):
        new_quiz = data["current_section_quizzes"][data["current_quiz_idx"]]
        await context.bot.send_message(chat_id, f"📌 Starting quiz {new_quiz['name']}!")
        logger.info(f"Next quiz: chat_id={chat_id}, quiz_idx={data['current_quiz_idx']}")
        questions = new_quiz["questions"].copy()
        random.shuffle(questions)
        data["questions"] = questions
        data["current_question"] = 0
        data["quiz_idx"] = data["current_quiz_idx"]
        data["poll_messages"] = {}
        data["correct_option_ids"] = {}
        await send_next_question(update, context, chat_id)
    else:
        await finish_quiz(update, context, chat_id)

async def finish_quiz(update: Update, context: CallbackContext, chat_id: int):
    if chat_id not in user_data:
        logger.warning(f"Could not find data to finish quiz: chat_id={chat_id}")
        return

    data = user_data[chat_id]
    data["is_running"] = False  # Stop the quiz process
    result = f"Section {data['section']} (Questions {data['start_idx'] + 1}-{data['end_idx']}) completed! Results:\n"
    ranking = sorted(data["users"].items(), key=lambda x: (x[1]["score"], -x[1]["overall_speed"]), reverse=True)

    if not ranking:
        result += "No one participated."
    else:
        for i, (user_id, info) in enumerate(ranking, 1):
            try:
                user = await context.bot.get_chat_member(chat_id, user_id)
                result += f"{i}. {user.user.first_name}: {info['score']} points (Avg speed: {info['overall_speed']:.2f} seconds)\n"
            except Exception as e:
                logger.error(f"Error getting user info: user_id={user_id}, error={e}")

    await context.bot.send_message(chat_id, result)
    logger.info(f"Quiz finished: chat_id={chat_id}, results sent")
    await clear_tasks(chat_id)
    del user_data[chat_id]

async def poll_answer_handler(update: Update, context: CallbackContext) -> None:
    poll_id = update.poll_answer.poll_id
    user_id = update.poll_answer.user.id
    answer = update.poll_answer.option_ids[0]

    chat_id = None
    for cid, data in user_data.items():
        if poll_id in data["poll_messages"]:
            chat_id = cid
            break

    if chat_id is None:
        logger.warning(f"Could not find chat_id for poll answer: poll_id={poll_id}")
        return

    data = user_data[chat_id]
    if poll_id not in data["poll_messages"]:
        logger.warning(f"Poll ID not found: chat_id={chat_id}, poll_id={poll_id}")
        return

    if "users" not in data:
        data["users"] = {}

    if user_id not in data["users"]:
        data["users"][user_id] = {"score": 0, "overall_speed": 0, "answers_count": 0}

    correct_option_id = data["correct_option_ids"][poll_id]
    user = data["users"][user_id]
    time_diff = (datetime.now() - data["start_time"]).total_seconds()

    if answer == correct_option_id:
        user["score"] += 1
    user["overall_speed"] = ((user["overall_speed"] * user["answers_count"]) + time_diff) / (user["answers_count"] + 1)
    user["answers_count"] += 1
    logger.info(f"Answer received: chat_id={chat_id}, user_id={user_id}, score={user['score']}")

    # Proceed to next question
    data["current_question"] += 1
    await send_next_question(update, context, chat_id)

async def view_ranking(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    logger.info(f"Ranking command: chat_id={chat_id}")
    if chat_id not in user_data:
        await context.bot.send_message(chat_id, "No active quiz right now.")
        return

    data = user_data[chat_id]
    result = "Current ranking:\n"
    ranking = sorted(data["users"].items(), key=lambda x: (x[1]["score"], -x[1]["overall_speed"]), reverse=True)

    if not ranking:
        result += "No one has participated yet."
    else:
        for i, (user_id, info) in enumerate(ranking, 1):
            try:
                user = await context.bot.get_chat_member(chat_id, user_id)
                result += f"{i}. {user.user.first_name}: {info['score']} points (Avg speed: {info['overall_speed']:.2f} seconds)\n"
            except Exception as e:
                logger.error(f"Error in ranking: user_id={user_id}, error={e}")

    await context.bot.send_message(chat_id, result)

async def clear_tasks(chat_id):
    if chat_id in user_data:
        data = user_data[chat_id]
        data["is_running"] = False  # Stop the quiz process
        logger.info(f"Tasks cleared: chat_id={chat_id}")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", restart_quiz))
    app.add_handler(CommandHandler("stop", stop_quiz))
    app.add_handler(CommandHandler("quizlist", view_quiz_list))
    app.add_handler(CommandHandler("ranking", view_ranking))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    async def on_startup():
        await set_bot_commands(app.bot)
    app.job_queue.run_once(lambda context: on_startup(), 0)

    def on_shutdown():
        for chat_id in list(user_data.keys()):
            asyncio.run_coroutine_threadsafe(clear_tasks(chat_id), app.loop)
            if chat_id in user_data:
                del user_data[chat_id]
    atexit.register(on_shutdown)

    def signal_handler(signum, frame):
        on_shutdown()
        raise SystemExit
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("Bot is running! 🚀")
    logger.info("Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
