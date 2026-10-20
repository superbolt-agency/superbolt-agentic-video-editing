# Brand house style for on-screen text

Exact brand, product and URL names, and the spelling market, for captions and overlays. `/ve-video-edit-general` loads a brand's row into the plan's `fix_words` before rendering, and `/video-qa` checks every caption and overlay against it. Rules: `video-editing-standards.md` sections 7.2 to 7.4.

Add a row the first time a reviewer corrects a name. **Code** is the prefix of your project codes (`video-qa` uses it to tell which brand a folder like `ACM08` belongs to). **Market** is `US` or `UK`; leave it blank until someone rules on it. The example row is fictional: replace it with your own brands.

| Brand | Code | House form (exactly as written) | Corrected from | Market |
| --- | --- | --- | --- | --- |
| AcmeSleep | ACM | AcmeSleep, acmesleep.com | Acme Sleep, acme sleep | US |
| Sarah Creal Beauty | SCB | Sarah Creal, Sarah Creal Beauty, sarahcrealbeauty.com, Eyes Up, Face Flex | Sarah Creel, Sarah Creole, Cerakriel | US |
