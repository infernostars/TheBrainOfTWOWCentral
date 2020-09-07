import discord, asyncio, io, aiohttp
from datetime import datetime
from Config._db import Database
from Config._functions import grammar_list
from Config._servers import MAIN_SERVER

class EVENT:
	db = Database()

	# Executes when loaded
	def __init__(self):
		self.RUNNING = False
		self.param = {
			"HOUR_SPEED": 6
		}

	# Executes when activated
	def start(self, SERVER): # Set the parameters
		self.SERVER = SERVER
		self.RUNNING = True

	
	# Executes when deactivated
	def end(self): # Reset the parameters
		self.RUNNING = False
	
	# Function that runs every hour
	async def on_one_hour(self):
		if "BANNER" not in self.SERVER["MAIN"].features:
			return
		
		current_time = datetime.utcnow()
		hour = current_time.hour

		if hour % self.param["HOUR_SPEED"] != 0:
			return
		
		banner_ind, banner_list = db.get_entries("tcbanner")[0]
		banner_list = banner_list.split(" ")

		banner_ind += 1
		banner_ind %= len(banner_list)

		new_banner = banner_list[banner_ind]

		db.edit_entry("tcbanner", entry={"current": banner_ind, "url": " ".join(banner_list)})

		async with aiohttp.ClientSession() as session:
			try:
				async with session.get(new_banner) as resp:
					if resp.status != 200:
						return
					
					data = io.BytesIO(await resp.read())
					await self.SERVER["MAIN"].edit(banner=data.read())
				
			except aiohttp.client_exceptions.InvalidURL:
				pass
		return

	# Change a parameter of the event
	async def edit_event(self, message, new_params):
		incorrect = []
		correct = []
		for parameter in new_params.keys():
			try:
				self.param[parameter] = new_params[parameter]
				correct.append(parameter)
			except KeyError:
				incorrect.append(parameter)
		
		if len(correct) > 0:
			await message.channel.send(f"Successfully changed the parameters: {grammar_list(correct)}")
		if len(incorrect) > 0:
			await message.channel.send(f"The following parameters are invalid: {grammar_list(incorrect)}")
		
		return
