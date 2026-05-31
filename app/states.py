from aiogram.fsm.state import State, StatesGroup


class StudentFSM(StatesGroup):
    choosing_subject = State()
    choosing_mode    = State()
    choosing_number  = State()
    choosing_topic   = State()
    solving          = State()
    mistakes_list    = State()
