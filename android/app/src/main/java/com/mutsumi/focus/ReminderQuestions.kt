package com.mutsumi.focus

import org.json.JSONObject
import kotlin.random.Random

internal data class ReminderQuestion(val body: String, val options: List<String>, val answer: Int)

internal object ReminderQuestions {
    private fun q(formula: String, answer: String, vararg wrong: String) =
        ReminderQuestion("当 x 趋近于 0 时，求下式的极限。\n\$\$\n$formula\n\$\$", listOf(answer, *wrong), 0)

    val builtIn = listOf(
        q("\\frac{\\sin x}{x}", "1", "0", "−1", "2"),
        q("\\frac{1-\\cos x}{x^2}", "1/2", "1", "−1/2", "0"),
        q("\\frac{e^x-1-x}{x^2}", "1/2", "1", "1/6", "0"),
        q("\\frac{x-\\sin x}{x^3}", "1/6", "−1/6", "1/2", "0"),
        q("\\frac{\\ln(1+x)-x}{x^2}", "−1/2", "1/2", "−1", "0"),
        q("\\frac{\\tan x-x}{x^3}", "1/3", "1/6", "−1/3", "1"),
        q("\\frac{\\sqrt{1+x}-1}{x}", "1/2", "−1/2", "1", "2"),
        q("\\frac{\\arctan x-x}{x^3}", "−1/3", "1/3", "−1/6", "0"),
        q("\\frac{\\cos x-1+x^2/2}{x^4}", "1/24", "−1/24", "1/6", "0"),
        q("\\frac{e^x-e^{-x}}{x}", "2", "1", "−2", "0"),
    )

    fun decode(raw: String): List<ReminderQuestion> = runCatching {
        val bank = JSONObject(raw).getJSONArray("questions")
        (0 until bank.length().coerceAtMost(48)).mapNotNull { index ->
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
    }.getOrDefault(emptyList())

    fun next(custom: List<ReminderQuestion>, previous: ReminderQuestion?, random: Random = Random.Default): ReminderQuestion {
        // Always retain known-good questions, including offline and after clear.
        val pool = (custom + builtIn).distinctBy { it.body }.filterNot { it.body == previous?.body }
        val question = pool.random(random)
        val order = question.options.indices.shuffled(random)
        return question.copy(options = order.map { question.options[it] }, answer = order.indexOf(question.answer))
    }
}
