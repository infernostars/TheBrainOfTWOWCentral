from random import choice, randint

github_devs = ["Infernity", "Digin", "LegitSi", "Zelo101", "Zettex", "woooowoooo", "pepsi", "Nv7", "Dark"] 
unfunny_errmsg = [
    "GOD FUCKING DAMMIT! **crashing noises**",
    "Whoops. You broke it.",
    "Perhaps some caffeinated beverages will provide some comic relief, hmm?",
    "..Shit.",
    "A fatal exception has occurred at memory address x0AAAAAAAH!",
    "Uh oh!",
    "Your bot ran into a problem and needs to be fixed. We're just collecting some error info, but we can't fix it for you.",
    "Have you tried turning it off and back on again?",
    "That's some pretty crappy reception if you ask me.",
    "Try smashing it, that will work!",
    "Bad bot!",
    "A fresh mind is exactly what you need to solve a problem!",
    "Are you *sure* it wasn't just a typo?",
    "I'm pretty sure it's just a typo.",
    "THREAD: 4 (BROKEN BOT EXCEPTION)",
    "Why not take a break? You can pause your session by leaving the room.",
    "0000000F\n00000003",
    "Your bot's code appears to be abnormal!",
    "I'm so sorry for all this.",
    ":(",
    "Me sad.",
    "404: Good code not found.",
    "I've had enough of this shit!",
    "An unexpected error occurred and the bot needs to quit. We're sorry!",
    "Bot cannot startup. Error code = 0x1.",
    "I ran out of error messages to show! Suggest me some new ones!",
    "Why aren't you working properly?!",
    "***AAAAAAAAA!!!***",
    "I don't wanna play this game anymore!",
    "Guess it was a bad day to code.",
    "I for one welcome our new robot overlorrrrrrrrrrrrrrr-",
    "May contain trace amounts of salt!",
    "Scream louder, I think it can hear you!",
    "Disconnected?! Will attempt to reconnect...",
    f"Have you considered asking {choice(github_devs)}?",
    f"{choice(github_devs)} is to blame!",
    "Aha! I found a technical issue!",
    "get rekt nerd cope skill issue",
    "You're starting to look like that Angry German Kid, calm down!",
    "Take a few deep breaths.. then SCREAM AT THE COMPUTER LOUDLY!",
    "99% done.. so close!",
    "It used to work five minutes ago!",
    "Uhh.. this is awkward..",
    "Day 527: I still haven't got the bot to work.",
    "This bot's about as unstable as the Stonk Market.",
    "[DEFINE broken \"It's broken..\"] [VAR broken]",
    "You can do it, I believe in you!",
    "I haven't seen an outage last this long since the Great ROBLOX Outage of 2021.",
    "You just started working, why are you not working again?!",
    f"{choice(github_devs)} needs to be fired for this! Or was it {choice(github_devs)} that did this? No, it was obviously {choice(github_devs)}! Wait.. no..",
    f"{choice(github_devs)} sabotaged the code!",
    "I have a good feeling your code is about as buggy as Windows ME.",
    "Ok, so if you want to fix this, all you need to do is",
    "take this L",
    "Do you notice your code is not working? If so, good! Please proceed to the keyboard smashing station ahead of you.",
    f"YOU CAUSED THIS, {choice(github_devs).upper()}!!",
    "Better not make that code worse...",
    "(insert message here)",
    "that code be looking like the battle pass",
    "If you're wondering why this \"unfunny\" error message is sooooo long, keep wondering. Yep, that's what I want you to do. You will never know why I randomly decided to make this error message this long, so keep wondering, and i'm out. See ya!",
    "I think the code gave the interpreter a heart attack.",
    "The unfunny happened.",
    "The calm before the storm... but the storm already happened.",
    "print(\"Code broke how sad...\")",
    "You're a surgeon now, dissect the code!",
    "Either the code broke or THE code broke.",
    "Print out your code. Then throw it in the fire.",
    "The time is <built-in function time>. Go to the gym already.",
    "Jeez, this code works just about as well as Sword Factory's databases!",
    "You know that I made that really long \"unfunny\" error message? Well, I have randomly decided to make this one even LONGER! And i'll NEVER, EVER, IN A THOUSAND THOUSAND YEARS tell you why I have decided such a fate for this poor little error message that will only be seen through chance. NEVER! Anyways i'm going to have to increase the length of this by a few orders of magnitude in order for this message to be perfectly long. And oh wait, I have just met my goal! So i'll be pardoning and make sure to do your daily wordle, dordle, quordle, octordle, sedecordle, wordle, globle, nerdle, and hordle AND your daily viewing session of the youtube channel jacksfilms.",
    f"{choice(github_devs).lower()}",
    "The choice has been made! The code shall break!",
    "hey code mind if you don't break please don't break i really want you to not break please don't break please don't please please please PLEASE **PLEASE**",
    f"Hey, at least you're not {choice(github_devs)}, right?",
    "Maybe some Bob Ross will cheer you up?",
    "Wanna break from the error messages? If you fix your code now and watch a short video, you'll recieve 30 minutes of error-free code.",
    "Implementing your code has caused an abnormality in the interpreter!",
    "OVERPRICED BASIC ERROR MESSAGE",
    "\"...ekorb edoc ehT\">:#,_@",
    "nawwww :skull:",
    "line break\nit is powerful",
    "\"RAW UNFORMATTED JSON\",",
    "Watch as we witness this coder in his natural habitat get angry.",
    "It just HAD TO BREAK?!",
    "The amount of work you're putting into this is great, you just need a little fixation.",
    "Make sure to approach the code calmly.",
    "?!",
    "'number'",
    "i love my arrays",
    "oY uﾋﾆeve ﾋﾟ?tnredea nreor･｣",
    "uoyevahcne tnuodere na orre!",
    "式ﾌ??ﾟｵ爾ﾐ芬｢?爾ｵﾙ爾ｾｱ爾ﾋ?ｮｪ｡爾ﾊﾙ式ｻ?式ｪ｡爾ﾑﾔｦｷ",
    "We're making things more awesome. Be back soon.",
    "MISSION FAILED",
    f"{choice(github_devs)}'s gonna kill {choice(github_devs)} for this..",
    f"I think {choice(github_devs)} is having a mental breakdown right now over this..",
    "This may be caused by temporary technical problems, bugs, or widespread political revolution.",
    "It's gotta be widespread political revolution that's causing this.",
    "*distant sounds of a catastrophic car crash*",
    "Just stick a random reference in there. They'll never figure out the source.",
    "ProgramDefinedException except broken code now counts as a [THROW].",
    "You know what? No. I'm not even gonna try and say anything funny, this is just atrocious.",
    "It's not like I can read this anyway.",
    "helicopter variables much?",
    "Either you've been at this for far too long, or you just got this error for the first time. In either case, welcome to this purgatory.",
    "bruh moment",
    "We need to talk. It's not about you, it's the code. It's absolutely awful and I can't stand it anymore!",
    "Read over your code again. Maybe you missed something.",
    "I don't know what you tried to give me, but it ain't working. Try again.",
    "u good?",
    "Just know that it's perfectly acceptable to take a break for as long you need.",
    "Holy s**t you did it!",
    "How the hell did you get over here mate?",
    "Apologies for the inconvenience, but we have absolutely no idea how you came here.",
    "name 'BStarProgramDefinedException' is not defined",
    "Tag element damage detected! ~ Anti-Code by BStar Programs",
    f"Error detected, shutting down in T-({random.randint(0,31)}) ~ Anti-Code by BStar Programs - Kung fu fighting errors since 2021"
    ]
