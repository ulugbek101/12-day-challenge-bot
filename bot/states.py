from aiogram.fsm.state import State, StatesGroup


class SubmitForm(StatesGroup):
    screenshot = State()
    full_name = State()
    phone = State()
    confirm = State()


class AdminInput(StatesGroup):
    search_query = State()
    reject_reason = State()
