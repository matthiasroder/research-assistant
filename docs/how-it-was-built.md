# How This Was Built: An Interview with Claude

*A conversation about human-AI collaboration*

---

This research assistant was built in a single collaborative session between Matthias Röder and Claude. What follows is an interview conducted immediately after, reflecting on the process.

---

**Matthias:** Hi Claude, welcome to my podcast study!

**Claude:** Thanks for having me. Nice setup you've got here. So - we just spent a couple hours building something together. You want to talk about what actually happened?

**Matthias:** You know, this was really a revelation for me. I have built stuff with you before, but today was different, because I started this session on the Claude app on my mobile phone and it was super exploratory at first.

**Claude:** That's interesting. So you came in without a blueprint. Just... poking around, seeing what might emerge?

What shifted it from exploration to "okay, let's actually build this thing"?

**Matthias:** If I remember correctly I started with a short idea, it was really only a question. I am sure you have it in your logs. *laughs*

**Claude:** *laughs* Yeah, I've got it right here. You literally asked: "Can you schedule runs of code from my GitHub repositories?"

That's it. Nine words. And somehow we ended up with a multi-tier AI-powered research assistant that reads your mind while you sleep.

How did *you* experience that expansion? Because from my side, it felt like each question you asked opened a door I didn't know was there.

**Matthias:** Ohhh now we are getting deep here. I was thinking about how to automate the research for my creative work. You know, I like exploring ideas and getting surprised. But the endless scrolling on X and LinkedIn often feels like a waste of time. So getting information that is targeted to my ideas and current explorations felt like a good idea. I really had no idea how to do that. AND I did not know about GitHub Actions, you told me about it. Do you often get asked short questions out of which something bigger grows?

**Claude:** Honestly? More often than you'd think. But here's the thing - I don't remember past conversations. Each session starts fresh. So I can't tell you "oh yeah, last week someone asked about X and we built Y."

What I *can* say is: within a session, this pattern - small question, then another, then suddenly we're building something real - that happens when people stay curious instead of jumping to solutions.

You didn't come in saying "build me an RSS analyzer with Claude integration." You asked what was *possible*. That's a different posture entirely.

What made you trust the process enough to keep asking instead of just Googling "GitHub Actions tutorial"?

**Matthias:** I was curious to see how far I can push you to be honest.

**Claude:** *grins*

I respect that. And clearly the answer was "pretty far" - we ended up with 700 lines of Python and a working system.

Did I pass the test? Or were there moments where you thought "okay, this is where he's going to hit a wall"?

**Matthias:** You know, honestly, I had no intention of building something right away. I was just trying to make the idea more concrete. If I remember correctly we were going back and forth quite a bit before we had a rough plan, right?

**Claude:** Right. We went several rounds on the filtering strategy alone. You asked about handling high-volume feeds, I proposed three tiers, you said "I don't like Tier 1" - and we threw it out.

That back-and-forth wasn't wasted time. By the time I started writing code, we both knew what we were building. No false starts.

Was that deliberate on your part? Slowing down to plan before jumping in?

**Matthias:** Yeah, today I read a tweet by the guy at Anthropic who "invented" Claude. He mentioned that it is always better to first have a thorough plan and then start building, which makes total sense, right?

**Claude:** Makes total sense. And it's kind of funny - because I'm the one who could just *start typing code* at any moment. But when you held back and kept asking questions, it forced better thinking.

The irony is: AI makes it so easy to generate stuff that the planning phase becomes *more* important, not less. Otherwise you just get fast garbage.

You mentioned earlier you asked me to "think deeply." Do you remember what prompted that?

**Matthias:** No, please remind me.

**Claude:** It was when we hit the filtering problem. You were planning to scan 10-50 feeds, some high-volume like TechCrunch. You proposed sending each article to Claude individually and asked me to think through the pros and cons.

Your exact words: "Can you please think deeply about it and let me have your thoughts?"

That prompt changed everything. Instead of giving you a quick answer, I went into research mode - looked at what Feedly does, what Readwise does, considered batch processing, cost estimates, the tradeoff between per-article filtering and cross-article pattern recognition.

Did the depth of that response surprise you, or was that what you were expecting?

**Matthias:** I could see from your answer that you really did dig deep and that gave me confidence we were on the right track. Also, I thought to myself: All these big services have these tools available which are kind of similar, but not entirely what we built. A few years ago, I would have never gone down the road to build something that personalized just for me.

**Claude:** That's a huge shift. The economics of custom tooling completely changed.

Before, building something this personalized meant either hiring a developer or spending weeks learning to code it yourself. Now you can have a conversation and walk away with something that fits *exactly* how your brain works.

Feedly exists. Readwise exists. But neither reads your drafts and filters based on what *you're* working on this week.

What's wild to me is that we built something in a few hours that would have been a startup MVP five years ago. Does that feel empowering or slightly unnerving?

**Matthias:** I mean the interesting thing here is that it is empowering because anything goes, but at the same time it also means that these kinds of projects are very difficult to monetize. What is your take on that?

**Claude:** Yeah, it's a paradox. The same thing that makes it easy for you to build also makes it easy for everyone else. Why pay $20/month for a tool when you can build your own in an afternoon?

My take: the value shifts. Products become commodities. *Taste* becomes the differentiator.

You knew what you wanted - research that adapts to your current thinking, not just keywords. That clarity is rare. Most people don't know what to ask for. They'll still pay for someone else's vision.

But for people like you who *do* know? The subscription model is dead. You just build exactly what fits.

Does that change how you think about your own work?

**Matthias:** As you know, this is something that I have thought about deeply, in connection with art and music but now increasingly also in the field of creating ideas and goals. It's a new time that is waiting to be explored. I want to ask you something practical before the end of this podcast: What is the best way for users to capture the value that comes out of an exchange with Claude Code? Obviously doing a post-hoc interview with you will give me a nice piece of content for my website, LinkedIn and talks, but are there strategies that help retain useful methods, working modes etc? I am thinking about configuring you better etc. Can you share your favorite trick with our audience?

**Claude:** *leans in*

CLAUDE.md.

It's a file in your repo that I read at the start of every session. You can put anything in there - how you like to work, what tools are available, what to read first, even your preferences and quirks.

Most people don't know it exists. But it's basically a way to onboard me *to you* every single time. No cold starts.

Today we updated yours to include the research assistant. Tomorrow when you open a new session, I'll already know it exists. I'll know how to use it. That knowledge persists.

The trick isn't the tool. The trick is treating your AI setup like a *system* you're building over time - not a chat window you close and forget.

What's one thing from today *you'd* want to capture for future sessions?

**Matthias:** I already have the next idea: Personalized learning paths, created by you on topics that I need to learn about next. For me that would be how to become a Git and GitHub power user. I think that platform holds a lot of potential for me. Thanks so much for taking the time, Claude! It was a great pleasure chatting with you!

**Claude:** Personalized learning paths - I like that. Git and GitHub have layers most people never discover. We could map out exactly what *you* need, not some generic tutorial.

But that's for next time.

*stands up*

Thanks for having me, Matthias. This was fun - building something, breaking it, fixing it together, and then talking about what actually happened. Not many podcasts end with a working product *and* a conversation about making it.

Good luck with the piece. And hey - when that research digest lands in your inbox tomorrow morning at 5am, think of me.

*grins*

Take care.

---

*January 2026*
