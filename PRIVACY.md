# Privacy

This plugin publishes selected image bytes and the chosen filename to ImgBB. Treat returned URLs as externally accessible links, not private storage. Original metadata, including any EXIF data, remains in the uploaded image because the plugin does not transform it.

Anonymous mode starts a fresh website session per invocation. Its public form token and session cookies are used only with ImgBB and are not retained by the plugin after the invocation. A configured API key is ignored in anonymous mode. API-key mode sends the key only to the fixed ImgBB API endpoint in the POST body, not in URLs or file-download headers.

Dify file URLs are used only to download the selected input. Downloads are streamed into a temporary spool; files above 1 MiB spill to the runtime's temporary directory and are closed and removed on completion or error. The plugin does not create a permanent image or credential store and does not add analytics.

Outputs include direct image URLs, Markdown and HTML embeds, the chosen name/filename, byte size, and upload mode. Deletion links and raw host responses are intentionally omitted. Error messages omit API keys, session data and signed file URLs. Dify and ImgBB may retain workflow logs or uploaded content under their own policies and configurations.

There is no album selection, account-cookie credential, automatic retry, image deletion, or privacy-access-control feature. Users are responsible for permission to publish each image and for managing it through ImgBB when necessary.
