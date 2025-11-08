import fasttext

# Загрузи модель
model = fasttext.load_model("/home/kano/git-dir/emet-bot/models/fasttext_news_classifier.bin")

def classify_news(text):
    predictions = model.predict(text, k=3)
    results = []
    for label, score in zip(predictions[0], predictions[1]):
        results.append({
            'category': label.replace('__label__', ''),
            'confidence': float(score)
        })
    return results

# Тестовые новости для разных категорий
test_news = "Российская национальная сборная по футболу одержала убедительную победу над соперником на чемпионате мира. Матч прошел в интенсивной борьбе, но наши игроки продемонстрировали высокий класс и тактическое мастерство. Главный тренер команды остался доволен результатом и выступлением своих подопечных."
for i in classify_news(test_news):
    print(i)