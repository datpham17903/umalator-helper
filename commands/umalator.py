import discord
import uuid
import json
import io
import os
import asyncio
from discord.ui import View
from utils.discord import command
from utils.db import SessionLocal, Preset
from utils.parse import parse_only_numbers
from opencv.veteran_umamusume_parsing import extract_image
from utils.blocking import run_blocking
from rapidfuzz import process, fuzz
from playwright.async_api import async_playwright

def fuzzy_match(a: str, b: list[str]):
    best_match, _, _ = process.extractOne(a, b, scorer=fuzz.WRatio)
    return best_match

async def input_name(page, info):
    umamusumes_dict = await page.evaluate('''
        [...document.querySelectorAll('.umaSuggestion')].map(e => [e.getAttribute("data-uma-id"), e.innerText]).reduce((a, [id, name]) => ({ ...a, [name.trim()]: id }), {})
    ''')
    umamusumes = list(umamusumes_dict.keys())
    true_name = fuzzy_match(info["name"], umamusumes)
    umamusume_id = umamusumes_dict[true_name]

    await page.locator('#umaPane > div.selected div.umaSelectorIconsBox img').first.click()
    await page.wait_for_timeout(300)
    await page.locator(f'#umaPane > div.selected .umaSuggestion[data-uma-id="{umamusume_id}"]').click()

async def input_skills(page, info):
    skills_dict = await page.evaluate('''
        [...document.querySelectorAll('#umaPane > div.selected .skillList .skill')].map(e => [e.getAttribute("data-skillid"), e.innerText]).reduce((a, [id, name]) => ({ ...a, [name]: id }), {})
    ''')
    unique_skill_name = await page.evaluate('''
        document.querySelector('div.skill.skill-unique').innerText
    ''')

    skills = list(skills_dict.keys())
    true_skills = set()
    for skill in info.get("skills", []):
        match = fuzzy_match(skill, skills)
        if match == unique_skill_name:
            continue
        true_skills.add(match)

    skills_ids = [skills_dict[skill] for skill in true_skills]

    for skill_id in skills_ids:
        await page.locator('#umaPane > div.selected button.skill.addSkillButton').click()
        await page.locator(f'#umaPane > div.selected .horseSkillPickerWrapper.open .skill[data-skillid="{skill_id}"]').click()

async def input_stats(page, info):
    stats = info.get("stats", {})
    if "Wisdom" not in stats and "Wit" in stats:
        stats["Wisdom"] = stats["Wit"]
    
    stat_order = ["Speed", "Stamina", "Power", "Guts", "Wisdom"]
    values = [stats.get(s, 0) for s in stat_order]
    
    all_inputs = await page.locator('.horseParam input[type="number"]').all()
    stat_inputs = []
    for inp in all_inputs:
        rect = await inp.bounding_box()
        if rect and 200 < rect['y'] < 250:
            stat_inputs.append(inp)
    
    for i, val in enumerate(values):
        if i < len(stat_inputs):
            await stat_inputs[i].fill(str(val))
            await page.wait_for_timeout(100)

async def get_presets(page):
    presets = await page.evaluate('''
        () => {
            const select = document.querySelectorAll('select')[4];
            if (!select) return [];
            return Array.from(select.options)
                .filter(o => o.value !== '-1' && o.text.trim())
                .map(o => o.text);
        }
    ''')
    return presets

async def input_preset(page, preset, custom_presets):
    if not preset.startswith("*"):
        # Alpha123: #P0-0 is input type=number, not select. Skip for built-in presets.
        return

    preset_name = preset[1:]
    custom_preset = [p for p in custom_presets if p.name == preset_name][0]

    await page.locator('.trackSelect > select[tabIndex="2"]').select_option(custom_preset.track_name)
    await page.locator('.trackSelect > select[tabIndex="3"]').select_option(custom_preset.track_length)
    await page.locator('select.groundSelect').select_option(custom_preset.ground)
    await page.locator(f'div.weatherSelect > img[title="{custom_preset.weather}"]').click()
    await page.locator(f'div.seasonSelect > img[title="{custom_preset.season}"]').click()

async def input_style(page, info, aptitude_idx_dict, style):
    style_map = {"Front": "Nige", "Pace": "Senkou", "Late": "Sasi", "End": "Oikomi"}
    style_apt = style_map.get(style, "Nige")
    
    style_tabindex = aptitude_idx_dict.get("Style")
    if style_tabindex:
        await page.evaluate(f'''
            () => {{
                const dropdown = document.querySelector('#umaPane > div.selected .horseAptitudeSelect[tabindex="{style_tabindex}"]');
                if (dropdown) {{
                    const option = [...dropdown.querySelectorAll('li[data-horse-aptitude]')]
                        .find(li => li.getAttribute('data-horse-aptitude') === '{style_apt}');
                    if (option) {{
                        dropdown.scrollIntoViewIfNeeded();
                        dropdown.click();
                        option.click();
                    }}
                }}
            }}
        ''')

async def input_surface_and_distance(page, info, aptitude_idx_dict):
    surface_apt = "1" if info.get("surface", "Turf") == "Turf" else "2"
    distance_apt = "0"
    dist_map = {"Sprint": "0", "Mile": "1", "Medium": "2", "Long": "3"}
    
    dist = info.get("distance", "Medium")
    distance_apt = dist_map.get(dist, "1")
    
    surface_tabindex = aptitude_idx_dict.get("Surface")
    if surface_tabindex:
        await page.evaluate(f'''
            () => {{
                const dropdown = document.querySelector('#umaPane > div.selected .horseAptitudeSelect[tabindex="{surface_tabindex}"]');
                if (dropdown) {{
                    const option = [...dropdown.querySelectorAll('li[data-horse-aptitude]')]
                        .find(li => li.getAttribute('data-horse-aptitude') === '{surface_apt}');
                    if (option) {{
                        dropdown.scrollIntoViewIfNeeded();
                        dropdown.click();
                        option.click();
                    }}
                }}
            }}
        ''')
    
    dist_tabindex = aptitude_idx_dict.get("Distance")
    if dist_tabindex:
        await page.evaluate(f'''
            () => {{
                const dropdown = document.querySelector('#umaPane > div.selected .horseAptitudeSelect[tabindex="{dist_tabindex}"]');
                if (dropdown) {{
                    const option = [...dropdown.querySelectorAll('li[data-horse-aptitude]')]
                        .find(li => li.getAttribute('data-horse-aptitude') === '{distance_apt}');
                    if (option) {{
                        dropdown.scrollIntoViewIfNeeded();
                        dropdown.click();
                        option.click();
                    }}
                }}
            }}
        ''')

async def compute_aptitude_dict(page):
    return await page.evaluate('''
        [...document.querySelectorAll('#umaPane > div.selected .horseAptitudes > div')]
            .map((e) => [e, e.querySelector('.horseAptitudeSelect')])
            .filter(([e, s]) => !!s)
            .map(([e, s]) => [e.innerText.split(' ')[0], s.getAttribute('tabindex')])
            .reduce((a, [key, value]) => ({ ...a, [key]: value }), {})
    ''')

async def simulate(page, samples=100):
    await page.locator('input#nsamples').fill(str(samples))
    await page.evaluate('document.querySelector("button#run").scrollIntoViewIfNeeded()')
    await page.locator('button#run').click(force=True)
    await page.wait_for_timeout(3000)

async def copy_link(page):
    try:
        copy_link = page.locator('a:has-text("Copy link")')
        await copy_link.scroll_into_view_if_needed()
        await page.wait_for_timeout(300)
        await copy_link.click()
        await page.wait_for_timeout(500)
        share_url = await page.evaluate('navigator.clipboard.readText()')
        return share_url if share_url else page.url
    except Exception as e:
        print(f"Error getting share URL: {e}")
        return page.url

async def setup_browser_and_page():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    context = await browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    page = await context.new_page()
    await page.set_viewport_size({"width": 1920, "height": 1080})
    await page.goto("https://alpha123.github.io/uma-tools/umalator-global/")
    await page.wait_for_timeout(1000)
    return pw, browser, page

async def extract_attachment_info(bot, attachment):
    file_path = f'./downloads/{uuid.uuid4()}.{attachment.content_type.split("/")[1]}'
    try:
        await attachment.save(file_path)
        info = await run_blocking(bot, extract_image, file_path)
        return info
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def hash_dict(info):
    return hash(tuple(sorted(info.items())))

async def extract_attachments(bot, attachments):
    ret = {}
    for attachment in attachments:
        try:
            info = await extract_attachment_info(bot, attachment)
            hash_info = hash(info["name"]) + hash_dict(info["stats"]) + hash_dict(info["aptitudes"])
            if hash_info not in ret:
                ret[hash_info] = info
            else:
                ret[hash_info]["skills"].extend(info["skills"])
        except Exception as e:
            print(f"Error extracting attachment: {e}")

    for info in ret.values():
        info["skills"] = list(set(info["skills"]))

    return list(ret.values())

def get_custom_presets():
    session = SessionLocal()
    try:
        return session.query(Preset).all()
    finally:
        session.close()

def get_uma_stats(uma):
    return f"{uma['stats']['Speed']}/{uma['stats']['Stamina']}/{uma['stats']['Power']}/{uma['stats']['Guts']}/{uma['stats']['Wit']}"

class StyleSelectView(View):
    def __init__(self, author_id):
        super().__init__(timeout=60)
        self.value = None
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Front", style=discord.ButtonStyle.primary)
    async def front(self, interaction, button):
        self.value = "Front"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Pace", style=discord.ButtonStyle.primary)
    async def pace(self, interaction, button):
        self.value = "Pace"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Late", style=discord.ButtonStyle.primary)
    async def late(self, interaction, button):
        self.value = "Late"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="End", style=discord.ButtonStyle.primary)
    async def end(self, interaction, button):
        self.value = "End"
        await interaction.response.defer()
        self.stop()

class PresetSelectView(View):
    def __init__(self, presets, author_id):
        super().__init__(timeout=60)
        self.value = None
        self.author_id = author_id
        
        for i, preset in enumerate(presets[:25]):
            button = discord.ui.Button(
                label=preset[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=str(i)
            )
            button.callback = self.create_callback(preset)
            self.add_item(button)

    def create_callback(self, preset):
        async def callback(interaction):
            self.value = preset
            await interaction.response.defer()
            self.stop()
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

async def select_style(channel, author_id, hint=""):
    view = StyleSelectView(author_id)
    prompt = f"Select the style for {hint}:" if hint else "Select the style:"
    prompt_msg = await channel.send(prompt, view=view)
    await view.wait()
    await prompt_msg.edit(view=None)
    
    if not view.value:
        await channel.send("No style selected, defaulting to Front.")
        return "Front"
    
    return view.value

async def select_preset(channel, presets, custom_presets, author_id):
    view = PresetSelectView(presets + [f"*{p.name}" for p in custom_presets], author_id)
    prompt_msg = await channel.send("Select the preset:", view=view)
    await view.wait()
    await prompt_msg.edit(view=None)
    
    if not view.value:
        await channel.send("No preset selected, defaulting to first preset.")
        return presets[0]
    
    return view.value

async def run_simulator_single(bot, uma, channel, message):
    await channel.send(f"Processing **{uma['name']}** ({get_uma_stats(uma)})...")

    pw, browser, page = await setup_browser_and_page()
    presets = await get_presets(page)
    custom_presets = get_custom_presets()

    await input_name(page, uma)
    await input_stats(page, uma)
    await input_skills(page, uma)

    style = await select_style(channel, message.author.id, uma['name'])
    preset = await select_preset(channel, presets, custom_presets, message.author.id)

    await input_preset(page, preset, custom_presets)
    aptitude_idx_dict = await compute_aptitude_dict(page)
    await input_style(page, uma, aptitude_idx_dict, style)
    await input_surface_and_distance(page, uma, aptitude_idx_dict)
    await simulate(page)
    
    screenshot = await page.screenshot()
    url = await copy_link(page)
    kachi_url = url.replace("alpha123.github.io/uma-tools", "kachi-dev.github.io/uma-tools")
    
    await channel.send(
        f"**{uma['name']}**\n"
        f"Simulator alpha123: [here]({url})\n"
        f"Simulator kachi-dev: [here]({kachi_url})",
        file=discord.File(io.BytesIO(screenshot), filename=f"{uma['name']}.png")
    )
    
    await browser.close()
    await pw.stop()

async def run_simulator_double(bot, uma1, uma2, channel, message):
    await channel.send(f"Comparing **{uma1['name']}** and **{uma2['name']}**...")

    pw, browser, page = await setup_browser_and_page()
    presets = await get_presets(page)
    custom_presets = get_custom_presets()

    await input_name(page, uma1)
    await input_skills(page, uma1)
    
    # Select first uma slot
    await page.locator('#umaPane > div.selected div.umaTab:has-text("Uma 1")').click()
    await input_name(page, uma1)
    await input_stats(page, uma1)
    await input_skills(page, uma1)

    # Select second uma slot  
    await page.locator('#umaPane > div.selected div.umaTab:has-text("Uma 2")').click()
    await input_name(page, uma2)
    await input_stats(page, uma2)
    await input_skills(page, uma2)

    style = await select_style(channel, message.author.id, "both")
    preset = await select_preset(channel, presets, custom_presets, message.author.id)

    await input_preset(page, preset, custom_presets)
    
    # Apply style/aptitudes for both
    aptitude_idx_dict = await compute_aptitude_dict(page)
    
    # Apply to Uma 1
    await page.locator('#umaPane > div.selected div.umaTab:has-text("Uma 1")').click()
    await input_style(page, uma1, aptitude_idx_dict, style)
    await input_surface_and_distance(page, uma1, aptitude_idx_dict)
    
    # Apply to Uma 2
    await page.locator('#umaPane > div.selected div.umaTab:has-text("Uma 2")').click()
    await input_style(page, uma2, aptitude_idx_dict, style)
    await input_surface_and_distance(page, uma2, aptitude_idx_dict)
    
    await simulate(page)
    
    screenshot = await page.screenshot()
    url = await copy_link(page)
    kachi_url = url.replace("alpha123.github.io/uma-tools", "kachi-dev.github.io/uma-tools")
    
    await channel.send(
        f"**{uma1['name']}** vs **{uma2['name']}**\n"
        f"Simulator alpha123: [here]({url})\n"
        f"Simulator kachi-dev: [here]({kachi_url})",
        file=discord.File(io.BytesIO(screenshot), filename="compare.png")
    )
    
    await browser.close()
    await pw.stop()

@command(name='umalator', description='Simulate Uma Musume from screenshot(s)')
async def umalator_command(interaction: discord.Interaction):
    attachments = []
    
    # Check if replying to a message with images
    if interaction.message.reference:
        try:
            replied_msg = await interaction.channel.fetch_message(interaction.message.reference.message_id)
            attachments = [att for att in replied_msg.attachments 
                         if att.content_type and att.content_type.startswith('image/')]
        except Exception:
            pass
    
    # If no attachments from reply, check current message
    if not attachments:
        attachments = [att for att in interaction.message.attachments 
                     if att.content_type and att.content_type.startswith('image/')]
    
    # If still no attachments, check for replied message that might have attachments
    # (mobile users often send images separately then reply with command)
    if not attachments and interaction.message.type == discord.MessageType.reply:
        try:
            # Try to get the original message content for images
            pass
        except Exception:
            pass
    
    if not attachments:
        await interaction.response.send_message(
            "Please reply to a message with image(s), or attach image(s) with the command.\n"
            "**Mobile:** Send images first, then reply to them with /umalator",
            ephemeral=True
        )
        return

    if len(attachments) > 10:
        await interaction.response.send_message("Maximum 10 images allowed.", ephemeral=True)
        return

    await interaction.response.send_message(f"Processing {len(attachments)} image(s)...", ephemeral=True)
    
    try:
        bot = interaction.client
        extracted = await extract_attachments(bot, attachments)
        
        if not extracted:
            await interaction.followup.send("No Uma Musume data extracted from images.")
            return
        
        channel = interaction.channel
        
        if len(extracted) == 1:
            await run_simulator_single(bot, extracted[0], channel, interaction.message)
        elif len(extracted) == 2:
            await run_simulator_double(bot, extracted[0], extracted[1], channel, interaction.message)
        else:
            await interaction.followup.send(f"Extracted {len(extracted)} Uma Musume. Maximum supported is 2 for comparison.")
            
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
