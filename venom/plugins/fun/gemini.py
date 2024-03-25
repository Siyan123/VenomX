import mimetypes
import pickle
from io import BytesIO

import google.generativeai as genai
from google.ai import generativelanguage as glm
from pyrogram import filters
from pyrogram.enums import ParseMode

from venom import Config, MyMessage, venom
from venom.core.methods.message.conversation import Conversation

GENERATION_CONFIG = {"temperature": 0.69, "max_output_tokens": 2048}

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]


TEXT_MODEL = genai.GenerativeModel(
    model_name="gemini-pro",
    generation_config=GENERATION_CONFIG,
    safety_settings=SAFETY_SETTINGS,
)

VISION_MODEL = genai.GenerativeModel(
    model_name="gemini-pro-vision",
    generation_config=GENERATION_CONFIG,
    safety_settings=SAFETY_SETTINGS,
)


async def init_task():
    if Config.GEMINI_API_KEY:
        genai.configure(api_key=Config.GEMINI_API_KEY)


async def basic_check(message: MyMessage):
    if not Config.GEMINI_API_KEY:
        await message.reply(
            "Gemini API KEY not found."
            "\nGet it <a href='https://makersuite.google.com/app/apikey'>HERE</a> "
            "and set GEMINI_API_KEY var."
        )
        return
    if not message.input_str:
        await message.reply("Ask a Question.")
        return
    return 1


@venom.trigger(cmd="ai")
async def question(_, message: MyMessage):
    """
    CMD: AI
    INFO: Ask a question to Gemini AI.
    USAGE: .ai what is the meaning of life.
    """

    if not (await basic_check(message)):  # fmt:skip
        return
    prompt = message.input_str

    reply = message.replied
    if reply and reply.photo:
        file = await reply.download(in_memory=True)

        mime_type, _ = mimetypes.guess_type(file.name)
        if mime_type is None:
            mime_type = "image/unknown"

        image_blob = glm.Blob(mime_type=mime_type, data=file.getvalue())
        response = await VISION_MODEL.generate_content_async([prompt, image_blob])

    else:
        response = await TEXT_MODEL.generate_content_async(prompt)

    response_text = get_response_text(response)
    reply_id = message.id if not message.replied else message.replied.id
    await venom.send_message(
        chat_id=message.chat.id,
        text=f"```\n{prompt}```**GEMINI AI**:\n{response_text.strip()}",
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=reply_id,
    )


@venom.trigger(cmd="aichat")
async def ai_chat(_, message: MyMessage):
    """
    CMD: AICHAT
    INFO: Have a Conversation with Gemini AI.
    USAGE:
        .aichat hello
        keep replying to AI responses
        After 5 mins of Idle bot will export history and stop chat.
        use .load_history to continue
    """
    if not (await basic_check(message)):  # fmt:skip
        return
    chat = TEXT_MODEL.start_chat(history=[])
    try:
        await do_convo(chat=chat, message=message)
    except TimeoutError:
        await export_history(chat, message)


@venom.trigger(cmd="load_history")
async def ai_chat(_, message: MyMessage):
    """
    CMD: LOAD_HISTORY
    INFO: Load a Conversation with Gemini AI from previous session.
    USAGE:
        .load_history {question} [reply to history document]
    """
    if not (await basic_check(message)):  # fmt:skip
        return
    reply = message.replied
    if (
        not reply
        or not reply.document
        or not reply.document.file_name
        or reply.document.file_name != "AI_Chat_History.pkl"
    ):
        await message.reply("Reply to a Valid History file.")
        return
    resp = await message.reply("<i>Loading History...</i>")
    doc: BytesIO = (await reply.download(in_memory=True)).getbuffer()  # NOQA
    history = pickle.loads(doc)
    await resp.edit("<i>History Loaded... Resuming chat</i>")
    chat = TEXT_MODEL.start_chat(history=history)
    try:
        await do_convo(chat=chat, message=message, history=True)
    except TimeoutError:
        await export_history(chat, message)


def get_response_text(response):
    return "\n".join([part.text for part in response.parts])


async def do_convo(chat, message: MyMessage, history: bool = False):
    prompt = message.input_str
    reply_to_message_id = message.id
    async with Conversation(
        client=venom,
        chat_id=message.chat.id,
        filters=generate_filter(message),
        timeout=300,
        check_for_duplicates=False,
    ) as convo:
        while True:
            ai_response = await chat.send_message_async(prompt)
            ai_response_text = get_response_text(ai_response)
            text = f"**GEMINI AI**:\n\n{ai_response_text}"
            _, prompt_message = await convo.send_message(
                text=text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=ParseMode.MARKDOWN,
                get_response=True,
            )
            prompt, reply_to_message_id = prompt_message.text, prompt_message.id


def generate_filter(message: MyMessage):
    async def _filter(_, __, msg: MyMessage):
        if (
            not msg.text
            or not msg.from_user
            or msg.from_user.id != message.from_user.id
            or not msg.reply_to_message
            or not msg.reply_to_message.from_user
            or msg.reply_to_message.from_user.id != venom.me.id
        ):
            return False
        return True

    return filters.create(_filter)


async def export_history(chat, message: MyMessage):
    doc = BytesIO(pickle.dumps(chat.history))
    doc.name = "AI_Chat_History.pkl"
    await venom.send_document(
        chat_id=message.from_user.id, document=doc, caption=message.text
    )
