package com.mutsumi.focus

import org.json.JSONObject
import kotlin.random.Random

internal data class ReminderQuestion(val body: String, val options: List<String>, val answer: Int)

internal object ReminderQuestions {
    private const val MAX_QUESTIONS = 512

    fun decode(raw: String): List<ReminderQuestion> =
        runCatching { decode(JSONObject(raw)) }.getOrDefault(emptyList())

    fun decode(payload: JSONObject): List<ReminderQuestion> {
        val bank = payload.optJSONArray("questions") ?: return emptyList()
        return (0 until bank.length().coerceAtMost(MAX_QUESTIONS)).mapNotNull { index ->
            runCatching {
                val row = bank.getJSONObject(index)
                val body = row.getString("body").takeIf { it.isNotBlank() && it.length <= 1120 } ?: return@runCatching null
                val values = row.getJSONArray("options")
                if (values.length() !in 3..5) return@runCatching null
                val options = (0 until values.length()).map(values::getString)
                val answer = row.getInt("answer_index")
                if (options.distinct().size != options.size || options.any { it.isBlank() || it.length > 160 } || answer !in options.indices)
                    return@runCatching null
                ReminderQuestion(body, options, answer)
            }.getOrNull()
        }
    }

    fun next(bank: List<ReminderQuestion>, previous: ReminderQuestion?, random: Random = Random.Default): ReminderQuestion? {
        val pool = if (bank.size > 1) bank.filterNot { it.body == previous?.body } else bank
        val question = pool.randomOrNull(random) ?: return null
        val order = question.options.indices.shuffled(random)
        return question.copy(options = order.map { question.options[it] }, answer = order.indexOf(question.answer))
    }
}
