# No-code setup guide

You don't need to know how to code, use GitHub or install anything on your computer.
Setup takes about 10 minutes. After that, using Readout is as simple as attaching files
to a chat with Claude.

> Claude's settings menus change from time to time. If a button in this guide has a
> slightly different name, look for the closest match on the same page.

## What you need

- A Claude account on a plan that includes skills. If you don't see a Skills option in
  your settings, your plan may not include it.
- Your data exports from Google Search Console, and optionally GA4 and Google Ads.
  [How to export them](exporting-data.md).

## Step 1: Download the skills

1. Go to the **Releases** page of this project. On the main GitHub page, it's in the right-hand
   column under "Releases". Click the latest version.
2. Under **Assets**, click each file to download it:
   - `readout-traffic-aggregator.zip`
   - `readout-change-explainer.zip`
3. Leave the files as they are. **Don't unzip them.**

> Don't use the green **Code** button on the main page. That downloads the whole project,
> which isn't the right file for Claude.

<!-- Screenshot: Releases page with the two zip files under Assets -->

## Step 2: Let Claude run code

Readout uses small programs to do its calculations, so Claude needs permission to run code.

1. Open Claude and go to **Settings**.
2. Open **Capabilities**.
3. Turn on **Code execution and file creation**.

<!-- Screenshot: Capabilities page with code execution turned on -->

## Step 3: Add the skills to Claude

1. In Claude, find **Skills**. Depending on your version, it's under **Customize** or under
   **Settings > Capabilities**.
2. Click **Create skill** (or **Upload skill**), then choose **Upload a skill**.
3. Select `readout-traffic-aggregator.zip`.
4. Repeat for `readout-change-explainer.zip`.
5. Make sure both skills are switched **on** in your skills list.

<!-- Screenshot: Skills list with both Readout skills switched on -->

## Step 4: Use it

Start a new chat, attach your export files, and ask in plain words. For example:

- *"Here are my GA4 and Search Console exports. Combine them and give me a summary."*
- *"Why did search traffic drop last month?"*
- *"Search clicks fell in October. What happened? Our brand name is Northwind."*

Claude will ask for anything it needs, such as your brand name or any recent changes to the
site, then give you a short answer. For the change explainer, ask for the **client report**
when you're ready to share it.

**Tip:** Readout works best with three Search Console exports: the last 28 days, the 28 days
before that, and the last 16 months. Upload all three at once.

## If something doesn't work

| What happened | What to try |
|---|---|
| Upload fails | Make sure you uploaded the zip file itself, not an unzipped folder, and that it came from the Releases page. |
| Claude doesn't seem to use Readout | Check both skills are switched on. Then mention it directly: *"Use the Readout change explainer on these files."* |
| Claude says a file wasn't recognized | Re-export the file without editing it. Opening and saving it in Excel can change its format. See the [export guide](exporting-data.md). |
| Claude can't run the analysis | Check that code execution is turned on (Step 2). |
| Numbers look wrong | Ask Claude to show the **Health check**. It lists missing dates and other data problems. |

## Updating to a new version

When a new version is released, download the new zip files from the Releases page. In your
skills list, remove the old Readout skills, then upload the new ones.

## Your data

Readout runs inside your own Claude chat. It doesn't send your data anywhere else. Your
exports are handled the same way as any other file you attach to Claude.
