            submitted_at = time.time()
            submission_id = hashlib.sha256(f"{guild_id}:{user.user_id}:{submitted_at}".encode()).hexdigest()[:24]
            is_change = bool(profile.get("pending_is_change"))
            payload_doc = {"courses": parsed, "proof_url": parsed[0]["proof_url"], "is_change": is_change, "submitted_at": submitted_at, "submission_id": submission_id}
            claim = await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_pending": {"$ne": True}}, {"$set": {"defense_review_pending": True, "defense_review_payload": payload_doc}})
            if getattr(claim, "modified_count", 0) != 1:
                raise web.HTTPConflict(text="Your defense submission is already pending staff review.")
            embeds = [discord.Embed(title="🛡️ Gauntlet Defense Change Request" if is_change else "🛡️ New Gauntlet Defense Placement Verification", description="A web submission is awaiting staff verification.", color=3447003)]
            embeds[0].add_field(name="Driver", value=f"<@{user.user_id}>", inline=False)
            embeds[0].set_footer(text=f"ALU Defense Submission: {submission_id}")
            for i, course in enumerate(parsed, 1):
                emb = discord.Embed(title=f"🏁 Course {i}: {course['track']}", description=f"🚗 **Car:** {course['car']}\n📈 **Car Performance:** {course['car_rank']}\n⏱️ **Lap Time:** {course['lap_time']}", color=3447003)
                emb.set_image(url=course["proof_url"])
                embeds.append(emb)
            try:
                from ..cogs.defense import DefenseView
                review_view = DefenseView(
                    str(user.user_id),
                    str(guild_id),
                    parsed,
                    parsed[0]["proof_url"],