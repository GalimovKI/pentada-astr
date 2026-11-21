"""Mail corpora available to the interactive and evaluation APIs."""
ARCHIVE_USER = "@archive"
PUBLIC_DATASET = "mail-public"


def mail_datasets(settings):
    datasets = {PUBLIC_DATASET: ("Почтовый поиск · публичный dev", settings.search_dataset, settings.database_url)}
    if not settings.enable_evaluations:
        return datasets
    for lang, name, url in (("ru", "русский перевод", settings.enronqa_ru_database_url),
                            ("en", "английский оригинал", settings.enronqa_en_database_url)):
        if url:
            archive = settings.enronqa_directory / f"enronqa-{lang}-{lang}.zip"
            datasets[f"enronqa-{lang}"] = (f"EnronQA · {name}", archive, url)
    return datasets
