package com.mutsumi.focus

import org.json.JSONObject
import kotlin.random.Random

internal data class ReminderQuestion(val body: String, val options: List<String>, val answer: Int)

internal object ReminderQuestions {
    private fun q(formula: String, answer: String, vararg wrong: String) =
        exercise("当 x 趋近于 0 时，求下式的极限。", formula, answer, *wrong)

    private fun exercise(prompt: String, formula: String, answer: String, vararg wrong: String) =
        ReminderQuestion("$prompt\n\$\$\n$formula\n\$\$", listOf(answer, *wrong), 0)

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

        exercise("直接计算下列定积分。", "∫₀¹ x dx", "1/2", "1", "1/3", "2"),
        exercise("直接计算下列定积分。", "∫₀¹ x² dx", "1/3", "1/2", "1/4", "2"),
        exercise("直接计算下列定积分。", "∫₀² 2x dx", "4", "2", "8", "1"),
        exercise("直接计算下列定积分。", "∫₀¹ (x+1) dx", "3/2", "1", "2", "1/2"),
        exercise("直接计算下列定积分。", "∫₀¹ (3x²+2) dx", "3", "2", "5/2", "4"),
        exercise("直接计算下列定积分。", "∫₀¹ (1−x) dx", "1/2", "1", "0", "−1/2"),
        exercise("直接计算下列定积分。", "∫₋₁¹ x dx", "0", "1", "2", "−1"),
        exercise("直接计算下列定积分。", "∫₋₁¹ x² dx", "2/3", "1/3", "1", "0"),
        exercise("计算从 0 到 π 的定积分。", "∫ sin x dx", "2", "1", "π", "0"),
        exercise("计算从 0 到 π/2 的定积分。", "∫ cos x dx", "1", "0", "π/2", "2"),
        exercise("直接计算下列定积分。", "∫₀¹ eˣ dx", "e−1", "1", "e", "1/2"),
        exercise("直接计算下列定积分。", "∫₀¹ (x²+x) dx", "5/6", "2/3", "1/2", "1"),
        exercise("直接计算下列定积分。", "∫₀¹ 4x³ dx", "1", "1/4", "2", "4"),
        exercise("直接计算下列定积分。", "∫₁² 1/x² dx", "1/2", "1", "1/4", "2"),

        exercise("计算下列有限等比级数的和。", "1+2+4+8", "15", "14", "16", "12"),
        exercise("计算下列有限等比级数的和。", "2+4+8+16", "30", "28", "32", "24"),
        exercise("计算下列有限等比级数的和。", "1+1/2+1/4", "7/4", "3/2", "5/4", "2"),
        exercise("计算下列有限等差级数的和。", "1+2+3+4+5", "15", "10", "20", "14"),
        exercise("计算下列有限等差级数的和。", "2+4+6+8", "20", "18", "16", "24"),
        exercise("计算下列有限等差级数的和。", "1+3+5+7+9", "25", "24", "20", "30"),
        exercise("计算下列有限级数的和。", "1+2+4+…+32", "63", "62", "64", "31"),
        exercise("计算下列有限级数的和。", "1²+2²+3²", "14", "12", "9", "36"),
        exercise("计算下列有限级数的和。", "1³+2³", "9", "8", "6", "12"),
        exercise("计算下列无穷等比级数的和。", "1/2+1/4+1/8+…", "1", "1/2", "2", "3/2"),
        exercise("计算下列无穷等比级数的和。", "1/3+1/9+1/27+…", "1/2", "1/3", "1", "2/3"),
        exercise("计算下列无穷等比级数的和。", "1+1/2+1/4+…", "2", "1", "3/2", "4"),
        exercise("计算下列有限级数的和。", "1−1+1−1+1−1", "0", "1", "−1", "2"),
        exercise("计算下列有限级数的和。", "1/2+2/3+3/4", "23/12", "19/12", "2", "7/6"),
        exercise("计算下列有限级数的和。", "1/2+1/6+1/12", "3/4", "2/3", "5/6", "1/2"),
        exercise("计算下列有限级数的和。", "1+1/3+1/9+1/27", "40/27", "13/9", "4/3", "3/2"),

        exercise("口算下列算式。", "25×16", "400", "360", "420", "250"),
        exercise("口算下列算式。", "99×9", "891", "900", "889", "981"),
        exercise("口算下列算式。", "48+57", "105", "95", "115", "104"),
        exercise("口算下列算式。", "125×8", "1000", "800", "1024", "125"),
        exercise("口算下列算式。", "√144", "12", "14", "72", "11"),
        exercise("口算下列算式。", "2⁵", "32", "16", "64", "25"),
        exercise("求下列方程的解。", "3x+2=11", "3", "2", "4", "−3"),
        exercise("求下列方程的解。", "2(x−1)=6", "4", "3", "2", "5"),
        exercise("计算下列导数。", "d(x²)/dx", "2x", "x", "x²", "2"),
        exercise("计算下列导数。", "d(sin x)/dx", "cos x", "−cos x", "sin x", "−sin x"),
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
